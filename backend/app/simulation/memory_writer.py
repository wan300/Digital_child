from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.graphiti_client import GraphitiClient
from app.clients.mem0_client import Mem0Client
from app.models.entities import Event, GraphEpisodeLink, MemoryRecord, SimAgent, SimulationEvent
from app.schemas.api import MemoryCandidate
from app.services.privacy_filter import PrivacyFilter


class SimulationMemoryWriter:
    def __init__(self) -> None:
        self.graphiti = GraphitiClient()
        self.mem0 = Mem0Client()
        self.privacy = PrivacyFilter()

    async def persist_event(self, session: AsyncSession, *, simulation_event: SimulationEvent) -> list[Event]:
        events: list[Event] = []
        if not self._is_durable(simulation_event):
            return events

        actor_ids = [item for item in simulation_event.actors if isinstance(item, str)]
        for agent_id in actor_ids:
            agent = await session.get(SimAgent, agent_id)
            if agent is None:
                continue
            local_event = Event(
                persona_id=agent.persona_id,
                conversation_id=None,
                event_type=f"simulation.{simulation_event.event_type}",
                source=simulation_event.source,
                reference_time=simulation_event.reference_time,
                payload={
                    "world_id": simulation_event.world_id,
                    "agent_id": agent.id,
                    "simulation_event_id": simulation_event.id,
                    "reference_time": simulation_event.reference_time.isoformat(),
                    "summary": simulation_event.payload.get("summary"),
                    "simulation_payload": simulation_event.payload,
                },
            )
            session.add(local_event)
            await session.flush()
            events.append(local_event)

            episode_uuid = await self.graphiti.add_episode(
                name=f"simulation:{simulation_event.world_id}:{simulation_event.id}:{agent.id}",
                body=self._episode_body(simulation_event),
                source_description="social simulation event",
                reference_time=simulation_event.reference_time,
                persona_id=agent.persona_id,
                counterparty_user_id=None,
            )
            session.add(
                GraphEpisodeLink(
                    event_id=local_event.id,
                    persona_id=agent.persona_id,
                    graph_group_id=self.graphiti.group_id(agent.persona_id),
                    graph_episode_uuid=episode_uuid,
                    reference_time=simulation_event.reference_time,
                )
            )
            await self._persist_memory_writes(session, simulation_event=simulation_event, local_event=local_event, default_agent=agent)
        return events

    def _is_durable(self, simulation_event: SimulationEvent) -> bool:
        if simulation_event.status == "needs_review":
            return False
        if simulation_event.event_type in {"agent_action", "conversation_message", "world_event", "rule_violation", "intervention_result", "random_event"}:
            return True
        return bool(simulation_event.payload.get("memory_writes"))

    def _episode_body(self, simulation_event: SimulationEvent) -> str:
        summary = simulation_event.payload.get("summary") or str(simulation_event.payload)
        return (
            f"World: {simulation_event.world_id}\n"
            f"Simulation event: {simulation_event.id}\n"
            f"Time: {simulation_event.reference_time.isoformat()}\n"
            f"Type: {simulation_event.event_type}\n"
            f"Summary: {summary}"
        )

    async def _persist_memory_writes(
        self,
        session: AsyncSession,
        *,
        simulation_event: SimulationEvent,
        local_event: Event,
        default_agent: SimAgent,
    ) -> None:
        writes = simulation_event.payload.get("memory_writes") or []
        if not isinstance(writes, list):
            return
        for item in writes:
            if not isinstance(item, dict):
                continue
            content = str(item.get("content") or "").strip()
            if not content:
                continue
            agent_id = str(item.get("agent_id") or default_agent.id)
            agent = default_agent if agent_id == default_agent.id else await session.get(SimAgent, agent_id)
            if agent is None:
                continue
            candidate = self.privacy.filter_candidate(
                MemoryCandidate(
                    content=content,
                    subject=f"persona:{agent.persona_id}",
                    memory_type=str(item.get("memory_type") or "event"),
                    confidence=float(item.get("confidence") or 0.7),
                    source_event_id=local_event.id,
                    decision="approved",
                    metadata={
                        "world_id": simulation_event.world_id,
                        "agent_id": agent.id,
                        "simulation_event_id": simulation_event.id,
                        "reference_time": simulation_event.reference_time.isoformat(),
                    },
                )
            )
            record = MemoryRecord(
                persona_id=agent.persona_id,
                counterparty_user_id=None,
                scope="persona",
                subject=candidate.subject,
                memory_type=candidate.memory_type,
                content=candidate.content,
                confidence=candidate.confidence,
                sensitivity=candidate.sensitivity,
                decision=candidate.decision,
                source_event_id=local_event.id,
                metadata_=candidate.metadata,
            )
            session.add(record)
            await session.flush()
            if record.decision == "approved":
                record.external_id = await self.mem0.add(
                    [{"role": "user", "content": record.content}],
                    user_id=record.subject,
                    agent_id=agent.persona_id,
                    run_id=None,
                    metadata={
                        "source_event_id": local_event.id,
                        "local_memory_id": record.id,
                        "world_id": simulation_event.world_id,
                        "simulation_event_id": simulation_event.id,
                    },
                )

