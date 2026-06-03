from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_admin
from app.clients.graphiti_client import GraphitiClient
from app.clients.letta_client import LettaClient
from app.clients.mem0_client import Mem0Client
from app.db.session import get_session
from app.models.entities import (
    AdminUser,
    CoreMemoryProposal,
    Event,
    GraphEpisodeLink,
    MemoryRecord,
    Persona,
    PersonaVersion,
)
from app.schemas.api import (
    CoreMemoryResponse,
    GeneratedPersonaCreate,
    MemoryCandidate,
    PersonaCreate,
    PersonaGenerateRequest,
    PersonaGenerateResponse,
    PersonaResponse,
    PersonaUpdate,
)
from app.services.persona_generator import (
    PersonaGenerationConfigError,
    PersonaGenerationError,
    PersonaGenerator,
    normalize_generated_memory,
)
from app.services.privacy_filter import PrivacyFilter

router = APIRouter(prefix="/personas", tags=["personas"], dependencies=[Depends(get_current_admin)])


@router.post("", response_model=PersonaResponse)
async def create_persona(payload: PersonaCreate, session: AsyncSession = Depends(get_session)) -> Persona:
    persona = Persona(**payload.model_dump())
    PrivacyFilter().validate_persona(persona)
    session.add(persona)
    await session.flush()
    session.add(PersonaVersion(persona_id=persona.id, version=1, snapshot=payload.model_dump(), reason="initial create"))
    await session.commit()
    await session.refresh(persona)
    return persona


@router.post("/generate-draft", response_model=PersonaGenerateResponse)
async def generate_persona_draft(payload: PersonaGenerateRequest) -> PersonaGenerateResponse:
    try:
        return await PersonaGenerator().generate(payload)
    except PersonaGenerationConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except PersonaGenerationError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/generated", response_model=PersonaResponse)
async def create_generated_persona(
    payload: GeneratedPersonaCreate,
    session: AsyncSession = Depends(get_session),
) -> Persona:
    persona = Persona(
        name=payload.name,
        description=payload.description,
        persona_type="fictional_persona",
        consent_confirmed=False,
        persona_block=payload.persona_block,
        human_block=payload.human_block,
    )
    privacy = PrivacyFilter()
    privacy.validate_persona(persona)
    session.add(persona)
    await session.flush()

    snapshot = payload.model_dump()
    snapshot["persona_type"] = persona.persona_type
    session.add(PersonaVersion(persona_id=persona.id, version=1, snapshot=snapshot, reason="generated create"))

    event = Event(
        persona_id=persona.id,
        conversation_id=None,
        event_type="generated_persona_seed",
        source="llm_persona_generator",
        payload={
            "name": payload.name,
            "description": payload.description,
            "memory_count": len(payload.memories),
        },
    )
    session.add(event)
    await session.flush()

    await _persist_generated_memories(session, persona, payload, event, privacy)
    await session.commit()
    await session.refresh(persona)
    return persona


@router.get("", response_model=list[PersonaResponse])
async def list_personas(session: AsyncSession = Depends(get_session)) -> list[Persona]:
    return (await session.execute(select(Persona).order_by(desc(Persona.updated_at)))).scalars().all()


@router.get("/{persona_id}", response_model=PersonaResponse)
async def get_persona(persona_id: str, session: AsyncSession = Depends(get_session)) -> Persona:
    persona = await session.get(Persona, persona_id)
    if persona is None:
        raise HTTPException(status_code=404, detail="人格不存在")
    return persona


@router.patch("/{persona_id}", response_model=PersonaResponse)
async def update_persona(persona_id: str, payload: PersonaUpdate, session: AsyncSession = Depends(get_session)) -> Persona:
    persona = await session.get(Persona, persona_id)
    if persona is None:
        raise HTTPException(status_code=404, detail="人格不存在")
    changes = payload.model_dump(exclude_unset=True)
    for key, value in changes.items():
        setattr(persona, key, value)
    PrivacyFilter().validate_persona(persona)
    session.add(
        PersonaVersion(
            persona_id=persona.id,
            version=1,
            snapshot={
                "name": persona.name,
                "description": persona.description,
                "persona_block": persona.persona_block,
                "human_block": persona.human_block,
                "changes": changes,
            },
            reason="manual update",
        )
    )
    await session.commit()
    await session.refresh(persona)
    return persona


@router.delete("/{persona_id}")
async def delete_persona(persona_id: str, session: AsyncSession = Depends(get_session)) -> dict[str, str]:
    persona = await session.get(Persona, persona_id)
    if persona is None:
        raise HTTPException(status_code=404, detail="人格不存在")
    await session.delete(persona)
    await session.commit()
    return {"status": "deleted"}


@router.post("/{persona_id}/initialize-agent", response_model=PersonaResponse)
async def initialize_agent(persona_id: str, session: AsyncSession = Depends(get_session)) -> Persona:
    persona = await session.get(Persona, persona_id)
    if persona is None:
        raise HTTPException(status_code=404, detail="人格不存在")
    PrivacyFilter().validate_persona(persona)
    persona.letta_agent_id = await LettaClient().ensure_agent(persona)
    persona.status = "active"
    await session.commit()
    await session.refresh(persona)
    return persona


@router.get("/{persona_id}/core-memory", response_model=CoreMemoryResponse)
async def core_memory(persona_id: str, session: AsyncSession = Depends(get_session)) -> CoreMemoryResponse:
    persona = await session.get(Persona, persona_id)
    if persona is None:
        raise HTTPException(status_code=404, detail="人格不存在")
    proposals = (
        await session.execute(
            select(CoreMemoryProposal).where(CoreMemoryProposal.persona_id == persona_id).order_by(desc(CoreMemoryProposal.created_at)).limit(20)
        )
    ).scalars().all()
    return CoreMemoryResponse(
        persona_id=persona.id,
        persona_block=persona.persona_block,
        human_block=persona.human_block,
        letta_agent_id=persona.letta_agent_id,
        proposals=proposals,
    )


@router.post("/{persona_id}/core-memory/proposals/{proposal_id}/approve", response_model=PersonaResponse)
async def approve_core_memory(
    persona_id: str,
    proposal_id: str,
    session: AsyncSession = Depends(get_session),
    _: AdminUser = Depends(get_current_admin),
) -> Persona:
    persona = await session.get(Persona, persona_id)
    proposal = await session.get(CoreMemoryProposal, proposal_id)
    if persona is None or proposal is None or proposal.persona_id != persona_id:
        raise HTTPException(status_code=404, detail="提案不存在")
    if proposal.target_block == "persona":
        proposal.old_text = persona.persona_block
        persona.persona_block = proposal.new_text
    elif proposal.target_block == "human":
        proposal.old_text = persona.human_block
        persona.human_block = proposal.new_text
    proposal.status = "approved"
    await session.commit()
    await session.refresh(persona)
    return persona


async def _persist_generated_memories(
    session: AsyncSession,
    persona: Persona,
    payload: GeneratedPersonaCreate,
    event: Event,
    privacy: PrivacyFilter,
) -> None:
    mem0 = Mem0Client()
    graphiti = GraphitiClient()
    subject = f"persona:{persona.id}"
    stored_contents: list[str] = []

    for draft in payload.memories:
        normalized = normalize_generated_memory(draft)
        if not normalized.content:
            continue
        candidate = privacy.filter_candidate(
            MemoryCandidate(
                content=normalized.content,
                subject=subject,
                memory_type=normalized.memory_type,
                confidence=normalized.confidence,
                source_event_id=event.id,
                decision="approved",
                metadata={"generated": True, "source": "llm_persona_generator"},
            )
        )
        record = MemoryRecord(
            persona_id=persona.id,
            counterparty_user_id=None,
            scope="persona",
            subject=subject,
            memory_type=candidate.memory_type,
            content=candidate.content,
            confidence=candidate.confidence,
            sensitivity=candidate.sensitivity,
            decision=candidate.decision,
            source_event_id=event.id,
            metadata_=candidate.metadata,
        )
        session.add(record)
        await session.flush()
        stored_contents.append(record.content)
        if record.decision == "approved":
            record.external_id = await mem0.add(
                [{"role": "user", "content": record.content}],
                user_id=subject,
                agent_id=persona.id,
                run_id=None,
                metadata={"source_event_id": event.id, "local_memory_id": record.id, "generated": True},
            )

    if stored_contents:
        episode_uuid = await graphiti.add_episode(
            name=f"generated-persona:{persona.id}:{event.id}",
            body="\n".join(stored_contents),
            source_description="generated persona seed memories",
            reference_time=event.reference_time,
            persona_id=persona.id,
            counterparty_user_id=None,
        )
        session.add(
            GraphEpisodeLink(
                event_id=event.id,
                persona_id=persona.id,
                graph_group_id=graphiti.group_id(persona.id),
                graph_episode_uuid=episode_uuid,
                reference_time=event.reference_time,
            )
        )
