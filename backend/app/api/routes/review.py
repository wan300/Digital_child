from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_admin
from app.clients.mem0_client import Mem0Client
from app.db.session import get_session
from app.models.entities import MemoryRecord
from app.schemas.api import MemoryRecordResponse

router = APIRouter(prefix="/review", tags=["review"], dependencies=[Depends(get_current_admin)])


@router.get("/memory-candidates", response_model=list[MemoryRecordResponse])
async def memory_candidates(session: AsyncSession = Depends(get_session)) -> list[MemoryRecord]:
    return (
        await session.execute(select(MemoryRecord).where(MemoryRecord.decision == "pending").order_by(desc(MemoryRecord.created_at)))
    ).scalars().all()


@router.post("/memory-candidates/{memory_id}/approve", response_model=MemoryRecordResponse)
async def approve_memory(memory_id: str, session: AsyncSession = Depends(get_session)) -> MemoryRecord:
    record = await session.get(MemoryRecord, memory_id)
    if record is None:
        raise HTTPException(status_code=404, detail="候选记忆不存在")
    record.decision = "approved"
    if not record.external_id:
        record.external_id = await Mem0Client().add(
            [{"role": "user", "content": record.content}],
            user_id=record.subject,
            agent_id=record.persona_id,
            run_id=None,
            metadata={"source_event_id": record.source_event_id, "local_memory_id": record.id},
        )
    await session.commit()
    await session.refresh(record)
    return record
