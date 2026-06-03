from __future__ import annotations

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.graphiti_client import GraphitiClient
from app.clients.mem0_client import Mem0Client
from app.models.entities import Event, GraphEpisodeLink, MemoryRecord, Message, Persona
from app.services.memory_extractor import MemoryExtractor


class MemoryWriter:
    def __init__(self) -> None:
        self.graphiti = GraphitiClient()
        self.mem0 = Mem0Client()
        self.extractor = MemoryExtractor()

    async def persist_turn(
        self,
        session: AsyncSession,
        *,
        persona: Persona,
        conversation_id: str,
        counterparty_user_id: str,
        user_message: Message,
        assistant_message: Message,
        reference_time: datetime,
    ) -> Event:
        event = Event(
            persona_id=persona.id,
            conversation_id=conversation_id,
            event_type="conversation_turn",
            source="web",
            reference_time=reference_time,
            payload={
                "counterparty_user_id": counterparty_user_id,
                "user_message_id": user_message.id,
                "assistant_message_id": assistant_message.id,
                "user": user_message.content,
                "assistant": assistant_message.content,
            },
        )
        session.add(event)
        await session.flush()

        episode_uuid = await self.graphiti.add_episode(
            name=f"conversation:{persona.id}:{conversation_id}:{event.id}",
            body=f"User said: {user_message.content}\nPersona replied: {assistant_message.content}",
            source_description="web chat session",
            reference_time=reference_time,
            persona_id=persona.id,
            counterparty_user_id=counterparty_user_id,
        )
        session.add(
            GraphEpisodeLink(
                event_id=event.id,
                persona_id=persona.id,
                graph_group_id=self.graphiti.group_id(persona.id, counterparty_user_id),
                graph_episode_uuid=episode_uuid,
                reference_time=reference_time,
            )
        )

        candidates = self.extractor.extract_from_turn(
            persona_id=persona.id,
            counterparty_user_id=counterparty_user_id,
            user_text=user_message.content,
            assistant_text=assistant_message.content,
            source_event_id=event.id,
        )
        for candidate in candidates:
            record = MemoryRecord(
                persona_id=persona.id,
                counterparty_user_id=counterparty_user_id,
                scope="human",
                subject=candidate.subject,
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
            if record.decision == "approved":
                external_id = await self.mem0.add(
                    [{"role": "user", "content": record.content}],
                    user_id=f"human:{counterparty_user_id}",
                    agent_id=persona.id,
                    run_id=conversation_id,
                    metadata={"source_event_id": event.id, "local_memory_id": record.id},
                )
                record.external_id = external_id
        return event
