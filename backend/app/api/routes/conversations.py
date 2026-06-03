from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_admin
from app.db.session import get_session
from app.models.entities import Conversation, Persona
from app.schemas.api import (
    ChatMessageCreate,
    ChatResponse,
    ConversationCreate,
    ConversationDetail,
    ConversationResponse,
)
from app.services.chat_service import ChatService

router = APIRouter(prefix="/conversations", tags=["conversations"], dependencies=[Depends(get_current_admin)])


@router.post("", response_model=ConversationResponse)
async def create_conversation(payload: ConversationCreate, session: AsyncSession = Depends(get_session)) -> Conversation:
    persona = await session.get(Persona, payload.persona_id)
    if persona is None:
        raise HTTPException(status_code=404, detail="人格不存在")
    conversation = Conversation(**payload.model_dump())
    session.add(conversation)
    await session.commit()
    await session.refresh(conversation)
    return conversation


@router.get("", response_model=list[ConversationResponse])
async def list_conversations(persona_id: str | None = None, session: AsyncSession = Depends(get_session)) -> list[Conversation]:
    stmt = select(Conversation).order_by(desc(Conversation.updated_at))
    if persona_id:
        stmt = stmt.where(Conversation.persona_id == persona_id)
    return (await session.execute(stmt)).scalars().all()


@router.get("/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(conversation_id: str, session: AsyncSession = Depends(get_session)) -> ConversationDetail:
    conversation = (
        await session.execute(select(Conversation).options(selectinload(Conversation.messages)).where(Conversation.id == conversation_id))
    ).scalar_one_or_none()
    if conversation is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    messages = sorted(conversation.messages, key=lambda message: message.created_at)
    return ConversationDetail.model_validate(conversation).model_copy(update={"messages": messages})


@router.post("/{conversation_id}/messages", response_model=ChatResponse)
async def send_message(conversation_id: str, payload: ChatMessageCreate, session: AsyncSession = Depends(get_session)) -> ChatResponse:
    try:
        return await ChatService().send_message(session, conversation_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
