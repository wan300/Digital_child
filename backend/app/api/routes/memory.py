from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_admin
from app.clients.mem0_client import Mem0Client
from app.db.session import get_session
from app.models.entities import MemoryRecord, Persona
from app.schemas.api import EvidenceItem, MemoryRecordResponse, MemorySearchRequest, TimelineSearchRequest
from app.services.context_builder import ContextBuilder

router = APIRouter(tags=["memory"], dependencies=[Depends(get_current_admin)])


@router.post("/memory/search", response_model=list[EvidenceItem])
async def search_memory(payload: MemorySearchRequest, session: AsyncSession = Depends(get_session)) -> list[EvidenceItem]:
    persona = await session.get(Persona, payload.persona_id)
    if persona is None:
        raise HTTPException(status_code=404, detail="人格不存在")
    bundle = await ContextBuilder().build(
        session,
        persona=persona,
        query=payload.query,
        counterparty_user_id=payload.counterparty_user_id,
        conversation_id=None,
    )
    return bundle.long_term_memories[: payload.k]


@router.get("/personas/{persona_id}/memories", response_model=list[MemoryRecordResponse])
async def list_memories(persona_id: str, decision: str | None = None, session: AsyncSession = Depends(get_session)) -> list[MemoryRecord]:
    stmt = select(MemoryRecord).where(MemoryRecord.persona_id == persona_id).order_by(desc(MemoryRecord.updated_at))
    if decision:
        stmt = stmt.where(MemoryRecord.decision == decision)
    return (await session.execute(stmt)).scalars().all()


@router.delete("/personas/{persona_id}/memories/{memory_id}")
async def delete_memory(persona_id: str, memory_id: str, session: AsyncSession = Depends(get_session)) -> dict[str, str]:
    record = await session.get(MemoryRecord, memory_id)
    if record is None or record.persona_id != persona_id:
        raise HTTPException(status_code=404, detail="记忆不存在")
    if record.external_id:
        await Mem0Client().delete(record.external_id)
    await session.delete(record)
    await session.commit()
    return {"status": "deleted"}


@router.get("/personas/{persona_id}/timeline", response_model=list[EvidenceItem])
async def timeline(persona_id: str, session: AsyncSession = Depends(get_session)) -> list[EvidenceItem]:
    persona = await session.get(Persona, persona_id)
    if persona is None:
        raise HTTPException(status_code=404, detail="人格不存在")
    return await ContextBuilder()._local_timeline(session, persona_id, None, "")


@router.post("/personas/{persona_id}/timeline/search", response_model=list[EvidenceItem])
async def search_timeline(persona_id: str, payload: TimelineSearchRequest, session: AsyncSession = Depends(get_session)) -> list[EvidenceItem]:
    persona = await session.get(Persona, persona_id)
    if persona is None:
        raise HTTPException(status_code=404, detail="人格不存在")
    bundle = await ContextBuilder().build(session, persona=persona, query=payload.query, counterparty_user_id=None, conversation_id=None)
    return bundle.temporal_facts[: payload.k]
