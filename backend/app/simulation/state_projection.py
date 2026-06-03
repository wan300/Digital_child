from __future__ import annotations

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.entities import (
    AgentRelationship,
    CommunityRule,
    GrowthReport,
    SimAgent,
    SimulationEvent,
    SimulationWorld,
    WorldLocation,
    WorldSnapshot,
)
from app.schemas.api import (
    AgentProjection,
    AgentRelationshipResponse,
    BranchPreviewResponse,
    ChildProjection,
    CommunityRuleResponse,
    GrowthReportResponse,
    SimAgentResponse,
    SimulationEventResponse,
    SimulationWorldResponse,
    WorldLocationResponse,
    WorldSnapshotResponse,
    WorldStateProjection,
)
from app.simulation.rulebook import Rulebook


class StateProjector:
    async def project(self, session: AsyncSession, world_id: str, *, event_limit: int = 20) -> WorldStateProjection:
        world = await session.get(SimulationWorld, world_id)
        if world is None:
            raise ValueError("world not found")
        locations = (
            await session.execute(select(WorldLocation).where(WorldLocation.world_id == world_id).order_by(WorldLocation.name))
        ).scalars().all()
        agents = (
            await session.execute(
                select(SimAgent)
                .options(selectinload(SimAgent.state))
                .where(SimAgent.world_id == world_id)
                .order_by(SimAgent.name)
            )
        ).scalars().all()
        rules = (
            await session.execute(select(CommunityRule).where(CommunityRule.world_id == world_id).order_by(CommunityRule.priority))
        ).scalars().all()
        events = (
            await session.execute(
                select(SimulationEvent)
                .where(SimulationEvent.world_id == world_id)
                .order_by(desc(SimulationEvent.reference_time), desc(SimulationEvent.created_at))
                .limit(event_limit)
            )
        ).scalars().all()
        child = self._find_child(world, list(agents))
        relationships = []
        reports = []
        snapshots = []
        child_projection = None
        if child is not None:
            relationships = (
                await session.execute(
                    select(AgentRelationship)
                    .where(AgentRelationship.world_id == world_id, AgentRelationship.child_agent_id == child.id)
                    .order_by(AgentRelationship.relationship_type, AgentRelationship.created_at)
                )
            ).scalars().all()
            reports = (
                await session.execute(
                    select(GrowthReport)
                    .where(GrowthReport.world_id == world_id, GrowthReport.child_agent_id == child.id)
                    .order_by(desc(GrowthReport.period_end_tick), desc(GrowthReport.created_at))
                    .limit(5)
                )
            ).scalars().all()
            snapshots = (
                await session.execute(
                    select(WorldSnapshot)
                    .where(WorldSnapshot.world_id == world_id)
                    .order_by(desc(WorldSnapshot.tick_no), desc(WorldSnapshot.created_at))
                    .limit(30)
                )
            ).scalars().all()
            child_location = next((location for location in locations if location.id == child.current_location_id), None)
            child_projection = ChildProjection(
                agent=SimAgentResponse.model_validate(child),
                location=WorldLocationResponse.model_validate(child_location) if child_location is not None else None,
                needs=child.state.needs if child.state else {},
                development=(child.state.metadata_ or {}).get("development", {}) if child.state else {},
                key_memories=(child.state.metadata_ or {}).get("key_memories", []) if child.state else [],
                half_day_summaries=(child.state.metadata_ or {}).get("half_day_summaries", []) if child.state else [],
            )
        active_rules = Rulebook().active_rules(list(rules), now=world.clock_time)
        return WorldStateProjection(
            world=SimulationWorldResponse.model_validate(world),
            locations=[WorldLocationResponse.model_validate(location) for location in locations],
            agents=[
                AgentProjection(
                    id=agent.id,
                    persona_id=agent.persona_id,
                    name=agent.name,
                    status=agent.status,
                    current_location_id=agent.current_location_id,
                    home_location_id=agent.home_location_id,
                    current_action=agent.state.current_action if agent.state else "",
                    mood=agent.state.mood if agent.state else "neutral",
                    goals=agent.goals,
                    traits=agent.traits,
                )
                for agent in agents
            ],
            rules=[CommunityRuleResponse.model_validate(rule) for rule in active_rules],
            recent_events=[SimulationEventResponse.model_validate(event) for event in events],
            child=child_projection,
            relationships=[AgentRelationshipResponse.model_validate(relationship) for relationship in relationships],
            growth_reports=[GrowthReportResponse.model_validate(report) for report in reports],
            snapshots=[WorldSnapshotResponse.model_validate(snapshot) for snapshot in snapshots],
            branch_preview=BranchPreviewResponse(world_id=world.id) if (world.settings or {}).get("world_type") == "child_growth_v1" else None,
        )

    def _find_child(self, world: SimulationWorld, agents: list[SimAgent]) -> SimAgent | None:
        child_id = (world.settings or {}).get("child_agent_id")
        for agent in agents:
            if agent.id == child_id or agent.metadata_.get("role") == "child" or agent.traits.get("role") == "child":
                return agent
        return None
