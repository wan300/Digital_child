from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_admin
from app.db.session import get_session
from app.models.entities import Persona
from app.schemas.api import (
    ContextBundle,
    DocumentSearchRequest,
    EvidenceItem,
    MemorySearchRequest,
    ToolBuildContextRequest,
)
from app.services.context_builder import ContextBuilder

router = APIRouter(prefix="/tools", tags=["tools"], dependencies=[Depends(get_current_admin)])


@router.post("/build_context", response_model=ContextBundle)
async def build_context(payload: ToolBuildContextRequest, session: AsyncSession = Depends(get_session)) -> ContextBundle:
    persona = await session.get(Persona, payload.persona_id)
    if persona is None:
        raise HTTPException(status_code=404, detail="人格不存在")
    return await ContextBuilder().build(
        session,
        persona=persona,
        query=payload.query,
        counterparty_user_id=payload.counterparty_user_id,
        conversation_id=payload.conversation_id,
    )


@router.post("/search_person_memory", response_model=list[EvidenceItem])
async def search_person_memory(payload: MemorySearchRequest, session: AsyncSession = Depends(get_session)) -> list[EvidenceItem]:
    bundle = await build_context(
        ToolBuildContextRequest(query=payload.query, persona_id=payload.persona_id, counterparty_user_id=payload.counterparty_user_id),
        session,
    )
    return bundle.long_term_memories[: payload.k]


@router.post("/search_timeline", response_model=list[EvidenceItem])
async def search_timeline(payload: MemorySearchRequest, session: AsyncSession = Depends(get_session)) -> list[EvidenceItem]:
    bundle = await build_context(
        ToolBuildContextRequest(query=payload.query, persona_id=payload.persona_id, counterparty_user_id=payload.counterparty_user_id),
        session,
    )
    return bundle.temporal_facts[: payload.k]


@router.post("/search_documents", response_model=list[EvidenceItem])
async def search_documents(payload: DocumentSearchRequest, session: AsyncSession = Depends(get_session)) -> list[EvidenceItem]:
    bundle = await build_context(ToolBuildContextRequest(query=payload.query, persona_id=payload.persona_id), session)
    return bundle.document_evidence[: payload.k]
