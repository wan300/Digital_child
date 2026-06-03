from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.clients.letta_client import LettaClient
from app.models.entities import Conversation, Message, Persona
from app.schemas.api import ChatMessageCreate, ChatResponse
from app.services.context_builder import ContextBuilder
from app.services.memory_writer import MemoryWriter
from app.services.privacy_filter import PrivacyFilter


class ChatService:
    def __init__(self) -> None:
        self.context_builder = ContextBuilder()
        self.letta = LettaClient()
        self.memory_writer = MemoryWriter()
        self.privacy = PrivacyFilter()

    async def send_message(self, session: AsyncSession, conversation_id: str, payload: ChatMessageCreate) -> ChatResponse:
        stmt = select(Conversation).options(selectinload(Conversation.persona)).where(Conversation.id == conversation_id)
        conversation = (await session.execute(stmt)).scalar_one_or_none()
        if conversation is None:
            raise ValueError("会话不存在。")
        persona: Persona = conversation.persona
        self.privacy.validate_persona(persona)

        if not persona.letta_agent_id:
            persona.letta_agent_id = await self.letta.ensure_agent(persona)

        reference_time = payload.reference_time or datetime.now(UTC)
        user_message = Message(conversation_id=conversation.id, role="user", content=payload.content, context={})
        session.add(user_message)
        await session.commit()
        await session.refresh(user_message)

        context_bundle = await self.context_builder.build(
            session,
            persona=persona,
            query=payload.content,
            counterparty_user_id=conversation.counterparty_user_id,
            conversation_id=conversation.id,
        )
        recent_messages = (
            await session.execute(
                select(Message)
                .where(Message.conversation_id == conversation.id, Message.id != user_message.id)
                .order_by(desc(Message.created_at))
                .limit(12)
            )
        ).scalars().all()
        recent_messages = list(reversed(recent_messages))
        assistant_text = await self.letta.send_message(persona, payload.content, context_bundle, recent_messages=recent_messages)
        assistant_message = Message(
            conversation_id=conversation.id,
            role="assistant",
            content=assistant_text,
            context=context_bundle.model_dump(mode="json"),
        )
        session.add(assistant_message)
        await session.commit()
        await session.refresh(assistant_message)

        try:
            await self.memory_writer.persist_turn(
                session,
                persona=persona,
                conversation_id=conversation.id,
                counterparty_user_id=conversation.counterparty_user_id,
                user_message=user_message,
                assistant_message=assistant_message,
                reference_time=reference_time,
            )
            await session.commit()
        except Exception:
            await session.rollback()
        return ChatResponse(user_message=user_message, assistant_message=assistant_message, context_bundle=context_bundle)
