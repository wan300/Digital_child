from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import AuthenticatedUser, get_current_user
from app.db.session import get_session
from app.models.entities import (
    AgentRelationship,
    AgentState,
    AuditLog,
    ChildWorldDraft,
    CommunityRule,
    GrowthReport,
    Persona,
    RandomEventTemplate,
    SimAgent,
    SimulationEvent,
    SimulationWorld,
    UserIntervention,
    WorldLocation,
    WorldSnapshot,
)
from app.schemas.api import (
    AgentRelationshipResponse,
    BranchPreviewRequest,
    BranchPreviewResponse,
    ChildWorldDraftConfirm,
    ChildWorldDraftRequest,
    ChildWorldDraftResponse,
    CommunityRuleCreate,
    CommunityRuleResponse,
    CommunityRuleUpdate,
    GrowthReportResponse,
    RandomEventTemplateCreate,
    RandomEventTemplateResponse,
    RandomEventTemplateUpdate,
    SimAgentCreate,
    SimAgentResponse,
    SimAgentUpdate,
    SimulationEventResponse,
    SimulationStepResponse,
    SimulationWorldCreate,
    SimulationWorldResponse,
    SimulationWorldUpdate,
    UserInterventionCreate,
    UserInterventionResponse,
    WorldLocationCreate,
    WorldLocationResponse,
    WorldSnapshotResponse,
    WorldStateProjection,
)
from app.services.privacy_filter import PrivacyFilter
from app.simulation.child_growth import ChildWorldDraftService, branch_preview
from app.simulation.engine import SimulationEngine
from app.simulation.intervention_service import InterventionService
from app.simulation.scheduler import SimulationScheduler
from app.simulation.state_projection import StateProjector

router = APIRouter(prefix="/worlds", tags=["simulation"], dependencies=[Depends(get_current_user)])


@router.post("", response_model=SimulationWorldResponse)
async def create_world(payload: SimulationWorldCreate, session: AsyncSession = Depends(get_session)) -> SimulationWorld:
    world = SimulationWorld(
        name=payload.name,
        clock_time=payload.clock_time or datetime.now(UTC),
        speed=payload.speed,
        seed=payload.seed,
        settings=payload.settings,
    )
    session.add(world)
    await session.commit()
    await session.refresh(world)
    return world


@router.get("", response_model=list[SimulationWorldResponse])
async def list_worlds(session: AsyncSession = Depends(get_session)) -> list[SimulationWorld]:
    return (await session.execute(select(SimulationWorld).order_by(desc(SimulationWorld.updated_at)))).scalars().all()


@router.post("/child-drafts", response_model=ChildWorldDraftResponse)
async def create_child_world_draft(
    payload: ChildWorldDraftRequest,
    session: AsyncSession = Depends(get_session),
    admin: AuthenticatedUser = Depends(get_current_user),
) -> ChildWorldDraft:
    draft = await ChildWorldDraftService().create_draft(session, payload)
    _audit(session, actor=admin.username, action="child_world.draft.create", target_id=draft.id, payload={"template_key": draft.template_key})
    await session.commit()
    await session.refresh(draft)
    return draft


@router.get("/child-drafts", response_model=list[ChildWorldDraftResponse])
async def list_child_world_drafts(session: AsyncSession = Depends(get_session)) -> list[ChildWorldDraft]:
    return (await session.execute(select(ChildWorldDraft).order_by(desc(ChildWorldDraft.created_at)).limit(50))).scalars().all()


@router.post("/child-drafts/{draft_id}/confirm", response_model=SimulationWorldResponse)
async def confirm_child_world_draft(
    draft_id: str,
    payload: ChildWorldDraftConfirm,
    session: AsyncSession = Depends(get_session),
    admin: AuthenticatedUser = Depends(get_current_user),
) -> SimulationWorld:
    draft = await session.get(ChildWorldDraft, draft_id)
    if draft is None:
        raise HTTPException(status_code=404, detail="儿童世界草稿不存在")
    try:
        world = await ChildWorldDraftService().confirm_draft(session, draft=draft, payload=payload, admin_actor=admin.username)
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await session.commit()
    await session.refresh(world)
    return world


@router.get("/{world_id}", response_model=SimulationWorldResponse)
async def get_world(world_id: str, session: AsyncSession = Depends(get_session)) -> SimulationWorld:
    return await _get_world(session, world_id)


@router.patch("/{world_id}", response_model=SimulationWorldResponse)
async def update_world(
    world_id: str,
    payload: SimulationWorldUpdate,
    session: AsyncSession = Depends(get_session),
    admin: AuthenticatedUser = Depends(get_current_user),
) -> SimulationWorld:
    world = await _get_world(session, world_id)
    changes = payload.model_dump(exclude_unset=True)
    for key, value in changes.items():
        setattr(world, key, value)
    _audit(session, actor=admin.username, action="simulation.world.update", target_id=world.id, payload=changes)
    await session.commit()
    await session.refresh(world)
    return world


@router.delete("/{world_id}", response_model=SimulationWorldResponse)
async def archive_world(
    world_id: str,
    session: AsyncSession = Depends(get_session),
    admin: AuthenticatedUser = Depends(get_current_user),
) -> SimulationWorld:
    world = await _get_world(session, world_id)
    world.status = "archived"
    _audit(session, actor=admin.username, action="simulation.world.archive", target_id=world.id, payload={})
    await session.commit()
    await session.refresh(world)
    return world


@router.post("/{world_id}/start", response_model=SimulationWorldResponse)
async def start_world(
    world_id: str,
    session: AsyncSession = Depends(get_session),
    admin: AuthenticatedUser = Depends(get_current_user),
) -> SimulationWorld:
    return await _set_world_status(session, world_id, "running", admin, "simulation.world.start")


@router.post("/{world_id}/pause", response_model=SimulationWorldResponse)
async def pause_world(
    world_id: str,
    session: AsyncSession = Depends(get_session),
    admin: AuthenticatedUser = Depends(get_current_user),
) -> SimulationWorld:
    return await _set_world_status(session, world_id, "paused", admin, "simulation.world.pause")


@router.post("/{world_id}/resume", response_model=SimulationWorldResponse)
async def resume_world(
    world_id: str,
    session: AsyncSession = Depends(get_session),
    admin: AuthenticatedUser = Depends(get_current_user),
) -> SimulationWorld:
    return await _set_world_status(session, world_id, "running", admin, "simulation.world.resume")


@router.post("/{world_id}/step", response_model=SimulationStepResponse)
async def step_world(world_id: str, session: AsyncSession = Depends(get_session)) -> SimulationStepResponse:
    scheduler = SimulationScheduler()
    async with scheduler.world_lock(world_id, blocking_timeout=2.0) as acquired:
        if not acquired:
            raise HTTPException(status_code=409, detail="world step already running")
        try:
            response = await SimulationEngine().step(session, world_id)
        except ValueError as exc:
            await session.rollback()
            raise HTTPException(status_code=404 if "not found" in str(exc) else 400, detail=str(exc)) from exc
        await session.commit()
        return response


@router.get("/{world_id}/state", response_model=WorldStateProjection)
async def world_state(world_id: str, session: AsyncSession = Depends(get_session)) -> WorldStateProjection:
    try:
        return await StateProjector().project(session, world_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{world_id}/events", response_model=list[SimulationEventResponse])
async def world_events(world_id: str, limit: int = 50, session: AsyncSession = Depends(get_session)) -> list[SimulationEvent]:
    await _get_world(session, world_id)
    capped = max(1, min(limit, 200))
    return (
        await session.execute(
            select(SimulationEvent)
            .where(SimulationEvent.world_id == world_id)
            .order_by(desc(SimulationEvent.reference_time), desc(SimulationEvent.created_at))
            .limit(capped)
        )
    ).scalars().all()


@router.get("/{world_id}/relationships", response_model=list[AgentRelationshipResponse])
async def world_relationships(world_id: str, session: AsyncSession = Depends(get_session)) -> list[AgentRelationship]:
    await _get_world(session, world_id)
    return (
        await session.execute(
            select(AgentRelationship).where(AgentRelationship.world_id == world_id).order_by(AgentRelationship.relationship_type, AgentRelationship.created_at)
        )
    ).scalars().all()


@router.get("/{world_id}/growth-reports", response_model=list[GrowthReportResponse])
async def world_growth_reports(world_id: str, session: AsyncSession = Depends(get_session)) -> list[GrowthReport]:
    await _get_world(session, world_id)
    return (
        await session.execute(
            select(GrowthReport).where(GrowthReport.world_id == world_id).order_by(desc(GrowthReport.period_end_tick), desc(GrowthReport.created_at))
        )
    ).scalars().all()


@router.get("/{world_id}/snapshots", response_model=list[WorldSnapshotResponse])
async def world_snapshots(world_id: str, session: AsyncSession = Depends(get_session)) -> list[WorldSnapshot]:
    await _get_world(session, world_id)
    return (
        await session.execute(
            select(WorldSnapshot).where(WorldSnapshot.world_id == world_id).order_by(desc(WorldSnapshot.tick_no), desc(WorldSnapshot.created_at)).limit(200)
        )
    ).scalars().all()


@router.post("/{world_id}/branches/preview", response_model=BranchPreviewResponse)
async def preview_branch(world_id: str, payload: BranchPreviewRequest, session: AsyncSession = Depends(get_session)) -> BranchPreviewResponse:
    await _get_world(session, world_id)
    return branch_preview(world_id, payload.snapshot_id)


@router.post("/{world_id}/locations", response_model=WorldLocationResponse)
async def create_location(
    world_id: str,
    payload: WorldLocationCreate,
    session: AsyncSession = Depends(get_session),
) -> WorldLocation:
    await _get_world(session, world_id)
    location = WorldLocation(
        world_id=world_id,
        name=payload.name,
        kind=payload.kind,
        x=payload.x,
        y=payload.y,
        description=payload.description,
        metadata_=payload.metadata,
    )
    session.add(location)
    await session.commit()
    await session.refresh(location)
    return location


@router.get("/{world_id}/locations", response_model=list[WorldLocationResponse])
async def list_locations(world_id: str, session: AsyncSession = Depends(get_session)) -> list[WorldLocation]:
    await _get_world(session, world_id)
    return (await session.execute(select(WorldLocation).where(WorldLocation.world_id == world_id).order_by(WorldLocation.name))).scalars().all()


@router.post("/{world_id}/agents", response_model=SimAgentResponse)
async def create_agent(
    world_id: str,
    payload: SimAgentCreate,
    session: AsyncSession = Depends(get_session),
) -> SimAgentResponse:
    await _get_world(session, world_id)
    persona = await session.get(Persona, payload.persona_id)
    if persona is None:
        raise HTTPException(status_code=404, detail="人格不存在")
    try:
        PrivacyFilter().validate_persona(persona)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await _validate_location(session, world_id, payload.home_location_id)
    await _validate_location(session, world_id, payload.current_location_id)
    first_location = (
        await session.execute(select(WorldLocation).where(WorldLocation.world_id == world_id).order_by(WorldLocation.name).limit(1))
    ).scalar_one_or_none()
    current_location_id = payload.current_location_id or payload.home_location_id or (first_location.id if first_location else None)
    agent = SimAgent(
        world_id=world_id,
        persona_id=persona.id,
        name=payload.name or persona.name,
        status=payload.status,
        home_location_id=payload.home_location_id,
        current_location_id=current_location_id,
        goals=payload.goals,
        traits=payload.traits,
        metadata_=payload.metadata,
    )
    session.add(agent)
    await session.flush()
    agent.state = AgentState(agent_id=agent.id)
    session.add(agent.state)
    await session.commit()
    agent = (
        await session.execute(select(SimAgent).options(selectinload(SimAgent.state)).where(SimAgent.id == agent.id))
    ).scalar_one()
    return SimAgentResponse.model_validate(agent)


@router.get("/{world_id}/agents", response_model=list[SimAgentResponse])
async def list_agents(world_id: str, session: AsyncSession = Depends(get_session)) -> list[SimAgent]:
    await _get_world(session, world_id)
    return (
        await session.execute(
            select(SimAgent).options(selectinload(SimAgent.state)).where(SimAgent.world_id == world_id).order_by(SimAgent.name)
        )
    ).scalars().all()


@router.patch("/{world_id}/agents/{agent_id}", response_model=SimAgentResponse)
async def update_agent(
    world_id: str,
    agent_id: str,
    payload: SimAgentUpdate,
    session: AsyncSession = Depends(get_session),
) -> SimAgentResponse:
    world = await _get_world(session, world_id)
    agent = (
        await session.execute(
            select(SimAgent).options(selectinload(SimAgent.state)).where(SimAgent.id == agent_id, SimAgent.world_id == world_id)
        )
    ).scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=404, detail="agent 不存在")
    changes = payload.model_dump(exclude_unset=True)
    if (
        (world.settings or {}).get("world_type") == "child_growth_v1"
        and (agent.traits.get("role") == "child" or agent.metadata_.get("role") == "child")
        and (world.status == "running" or world.tick_no > 0)
    ):
        raise HTTPException(status_code=400, detail="儿童世界启动后不能通过普通观察流程直接编辑儿童状态。")
    for key, value in changes.items():
        setattr(agent, "metadata_" if key == "metadata" else key, value)
    await session.commit()
    agent = (
        await session.execute(select(SimAgent).options(selectinload(SimAgent.state)).where(SimAgent.id == agent.id))
    ).scalar_one()
    return SimAgentResponse.model_validate(agent)


@router.post("/{world_id}/rules", response_model=CommunityRuleResponse)
async def create_rule(
    world_id: str,
    payload: CommunityRuleCreate,
    session: AsyncSession = Depends(get_session),
    admin: AuthenticatedUser = Depends(get_current_user),
) -> CommunityRule:
    await _get_world(session, world_id)
    rule = CommunityRule(
        world_id=world_id,
        title=payload.title,
        content=payload.content,
        priority=payload.priority,
        status=payload.status,
        effective_from=payload.effective_from,
        metadata_=payload.metadata,
    )
    session.add(rule)
    await session.flush()
    _audit(session, actor=admin.username, action="simulation.rule.create", target_id=world_id, payload={"rule_id": rule.id})
    await session.commit()
    await session.refresh(rule)
    return rule


@router.get("/{world_id}/rules", response_model=list[CommunityRuleResponse])
async def list_rules(world_id: str, session: AsyncSession = Depends(get_session)) -> list[CommunityRule]:
    await _get_world(session, world_id)
    return (await session.execute(select(CommunityRule).where(CommunityRule.world_id == world_id).order_by(CommunityRule.priority))).scalars().all()


@router.patch("/{world_id}/rules/{rule_id}", response_model=CommunityRuleResponse)
async def update_rule(
    world_id: str,
    rule_id: str,
    payload: CommunityRuleUpdate,
    session: AsyncSession = Depends(get_session),
    admin: AuthenticatedUser = Depends(get_current_user),
) -> CommunityRule:
    await _get_world(session, world_id)
    rule = (await session.execute(select(CommunityRule).where(CommunityRule.id == rule_id, CommunityRule.world_id == world_id))).scalar_one_or_none()
    if rule is None:
        raise HTTPException(status_code=404, detail="规则不存在")
    changes = payload.model_dump(exclude_unset=True)
    for key, value in changes.items():
        setattr(rule, "metadata_" if key == "metadata" else key, value)
    _audit(session, actor=admin.username, action="simulation.rule.update", target_id=world_id, payload={"rule_id": rule.id, "changes": changes})
    await session.commit()
    await session.refresh(rule)
    return rule


@router.post("/{world_id}/random-events", response_model=RandomEventTemplateResponse)
async def create_random_event(
    world_id: str,
    payload: RandomEventTemplateCreate,
    session: AsyncSession = Depends(get_session),
) -> RandomEventTemplate:
    await _get_world(session, world_id)
    template = RandomEventTemplate(world_id=world_id, **payload.model_dump())
    session.add(template)
    await session.commit()
    await session.refresh(template)
    return template


@router.get("/{world_id}/random-events", response_model=list[RandomEventTemplateResponse])
async def list_random_events(world_id: str, session: AsyncSession = Depends(get_session)) -> list[RandomEventTemplate]:
    await _get_world(session, world_id)
    return (
        await session.execute(select(RandomEventTemplate).where(RandomEventTemplate.world_id == world_id).order_by(RandomEventTemplate.name))
    ).scalars().all()


@router.patch("/{world_id}/random-events/{template_id}", response_model=RandomEventTemplateResponse)
async def update_random_event(
    world_id: str,
    template_id: str,
    payload: RandomEventTemplateUpdate,
    session: AsyncSession = Depends(get_session),
) -> RandomEventTemplate:
    await _get_world(session, world_id)
    template = (
        await session.execute(select(RandomEventTemplate).where(RandomEventTemplate.id == template_id, RandomEventTemplate.world_id == world_id))
    ).scalar_one_or_none()
    if template is None:
        raise HTTPException(status_code=404, detail="随机事件模板不存在")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(template, key, value)
    await session.commit()
    await session.refresh(template)
    return template


@router.post("/{world_id}/interventions", response_model=UserInterventionResponse)
async def create_intervention(
    world_id: str,
    payload: UserInterventionCreate,
    session: AsyncSession = Depends(get_session),
    admin: AuthenticatedUser = Depends(get_current_user),
) -> UserIntervention:
    world = await _get_world(session, world_id)
    try:
        intervention = await InterventionService().create(session, world=world, payload=payload, admin_actor=admin.username)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await session.commit()
    await session.refresh(intervention)
    return intervention


@router.get("/{world_id}/interventions", response_model=list[UserInterventionResponse])
async def list_interventions(world_id: str, session: AsyncSession = Depends(get_session)) -> list[UserIntervention]:
    await _get_world(session, world_id)
    return (
        await session.execute(select(UserIntervention).where(UserIntervention.world_id == world_id).order_by(desc(UserIntervention.created_at)))
    ).scalars().all()


async def _get_world(session: AsyncSession, world_id: str) -> SimulationWorld:
    world = await session.get(SimulationWorld, world_id)
    if world is None:
        raise HTTPException(status_code=404, detail="world 不存在")
    return world


async def _set_world_status(
    session: AsyncSession,
    world_id: str,
    status: str,
    admin: AuthenticatedUser,
    action: str,
) -> SimulationWorld:
    world = await _get_world(session, world_id)
    if world.status == "archived":
        raise HTTPException(status_code=400, detail="archived worlds cannot change status")
    world.status = status
    _audit(session, actor=admin.username, action=action, target_id=world.id, payload={"status": status})
    await session.commit()
    await session.refresh(world)
    return world


async def _validate_location(session: AsyncSession, world_id: str, location_id: str | None) -> None:
    if location_id is None:
        return
    location = await session.get(WorldLocation, location_id)
    if location is None or location.world_id != world_id:
        raise HTTPException(status_code=400, detail="location 不属于该 world")


def _audit(session: AsyncSession, *, actor: str, action: str, target_id: str, payload: dict) -> None:
    session.add(AuditLog(actor=actor, action=action, target_type="simulation_world", target_id=target_id, payload=payload))
