from __future__ import annotations

import random
from datetime import timedelta
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.clients.letta_client import LettaClient
from app.core.config import get_settings
from app.models.entities import (
    AgentState,
    CommunityRule,
    Persona,
    RandomEventTemplate,
    SimAgent,
    SimulationAction,
    SimulationEvent,
    SimulationWorld,
    UserIntervention,
    WorldLocation,
    WorldSnapshot,
)
from app.schemas.api import SimulationEventResponse, SimulationStepResponse, SimulationWorldResponse
from app.services.context_builder import ContextBuilder
from app.simulation.child_growth import ChildGrowthStepper, is_child_growth_world
from app.simulation.concordia_adapter import ConcordiaAdapter
from app.simulation.memory_writer import SimulationMemoryWriter
from app.simulation.random_events import RandomEventScheduler
from app.simulation.rulebook import Rulebook
from app.simulation.state_projection import StateProjector


class SimulationEngine:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.adapter = ConcordiaAdapter()
        self.rulebook = Rulebook()
        self.random_events = RandomEventScheduler()
        self.projector = StateProjector()
        self.memory_writer = SimulationMemoryWriter()
        self.context_builder = ContextBuilder()
        self.letta = LettaClient()

    async def step(self, session: AsyncSession, world_id: str) -> SimulationStepResponse:
        world = await session.get(SimulationWorld, world_id)
        if world is None:
            raise ValueError("world not found")
        if world.status == "archived":
            raise ValueError("archived worlds cannot be stepped")
        if is_child_growth_world(world):
            return await ChildGrowthStepper().step(session, world)

        tick_no = world.tick_no + 1
        reference_time = world.clock_time + timedelta(minutes=self.settings.simulation_step_minutes)
        rng = random.Random(f"{world.seed}:{tick_no}")

        locations = (
            await session.execute(select(WorldLocation).where(WorldLocation.world_id == world_id).order_by(WorldLocation.name))
        ).scalars().all()
        agents = (
            await session.execute(
                select(SimAgent)
                .options(selectinload(SimAgent.persona), selectinload(SimAgent.state))
                .where(SimAgent.world_id == world_id, SimAgent.status == "active")
                .order_by(SimAgent.name)
            )
        ).scalars().all()
        rules = (
            await session.execute(select(CommunityRule).where(CommunityRule.world_id == world_id).order_by(CommunityRule.priority))
        ).scalars().all()
        templates = (
            await session.execute(select(RandomEventTemplate).where(RandomEventTemplate.world_id == world_id).order_by(RandomEventTemplate.name))
        ).scalars().all()
        pending_interventions = (
            await session.execute(
                select(UserIntervention)
                .where(UserIntervention.world_id == world_id, UserIntervention.status == "pending")
                .order_by(UserIntervention.created_at)
            )
        ).scalars().all()
        recent_events = await self._recent_events(session, world_id)
        active_rules = self.rulebook.active_rules(list(rules), now=world.clock_time)

        created_events: list[SimulationEvent] = []
        for agent in self._select_agents(list(agents), rng):
            event = await self._step_agent(
                session,
                world=world,
                agent=agent,
                locations=list(locations),
                rules=active_rules,
                recent_events=recent_events,
                interventions=list(pending_interventions),
                rng=rng,
                tick_no=tick_no,
                reference_time=reference_time,
            )
            created_events.append(event)

        for template in self.random_events.due_templates(list(templates), tick_no=tick_no, clock_time=reference_time, rng=rng):
            event = await self._step_random_event(
                session,
                world=world,
                template=template,
                locations=list(locations),
                rules=active_rules,
                recent_events=recent_events,
                interventions=list(pending_interventions),
                tick_no=tick_no,
                reference_time=reference_time,
            )
            created_events.append(event)

        if not created_events:
            created_events.append(await self._idle_event(session, world=world, tick_no=tick_no, reference_time=reference_time))

        for intervention in pending_interventions:
            intervention.status = "applied"
            intervention.result_event_id = created_events[-1].id

        world.tick_no = tick_no
        world.clock_time = reference_time
        await session.flush()
        await self._maybe_snapshot(session, world=world, event_cursor=created_events[-1].id)
        state = await self.projector.project(session, world.id)
        return SimulationStepResponse(
            world=SimulationWorldResponse.model_validate(world),
            events=[SimulationEventResponse.model_validate(event) for event in created_events],
            state=state,
        )

    async def _step_agent(
        self,
        session: AsyncSession,
        *,
        world: SimulationWorld,
        agent: SimAgent,
        locations: list[WorldLocation],
        rules: list[CommunityRule],
        recent_events: list[SimulationEvent],
        interventions: list[UserIntervention],
        rng: random.Random,
        tick_no: int,
        reference_time,
    ) -> SimulationEvent:
        state = await self._ensure_agent_state(session, agent)
        next_location = self._choose_next_location(agent, locations, rng)
        observation = self._build_observation(
            world=world,
            agent=agent,
            locations=locations,
            rules=rules,
            recent_events=recent_events,
            interventions=interventions,
            suggested_location=next_location,
        )
        action_text, source = await self._intended_action(session, agent=agent, observation=observation, fallback_location=next_location)
        action = SimulationAction(
            world_id=world.id,
            agent_id=agent.id,
            action_text=action_text,
            status="proposed",
            source=source,
            context=observation,
        )
        session.add(action)
        await session.flush()
        outcome = await self.adapter.resolve_action(context=observation, action_text=action_text)
        self._apply_outcome(agent=agent, state=state, outcome=outcome)
        action.status = self._action_status(outcome)
        action.result = outcome
        event = await self._create_event(
            session,
            world=world,
            tick_no=tick_no,
            reference_time=reference_time,
            event_type="agent_action",
            source=action.source,
            actors=[agent.id],
            location_id=agent.current_location_id,
            payload={
                "action_id": action.id,
                "action_text": action.action_text,
                **outcome,
            },
        )
        await self._persist_memory(session, event)
        return event

    async def _step_random_event(
        self,
        session: AsyncSession,
        *,
        world: SimulationWorld,
        template: RandomEventTemplate,
        locations: list[WorldLocation],
        rules: list[CommunityRule],
        recent_events: list[SimulationEvent],
        interventions: list[UserIntervention],
        tick_no: int,
        reference_time,
    ) -> SimulationEvent:
        action_text = template.effect_prompt or f"Random event occurs: {template.name}"
        context = {
            "world": self._world_context(world),
            "agent": None,
            "locations": self._locations_context(locations),
            "rules": self.rulebook.to_context(rules),
            "recent_events": self._events_context(recent_events),
            "interventions": self._interventions_context(interventions),
            "random_event_template": {
                "id": template.id,
                "name": template.name,
                "severity": template.severity,
                "trigger": template.trigger,
            },
        }
        action = SimulationAction(
            world_id=world.id,
            agent_id=None,
            action_text=action_text,
            status="proposed",
            source="random_event",
            context=context,
        )
        session.add(action)
        await session.flush()
        outcome = await self.adapter.resolve_action(context=context, action_text=action_text)
        action.status = self._action_status(outcome)
        action.result = outcome
        event = await self._create_event(
            session,
            world=world,
            tick_no=tick_no,
            reference_time=reference_time,
            event_type="random_event",
            source="random_event",
            actors=[],
            location_id=None,
            payload={
                "template_id": template.id,
                "action_id": action.id,
                "action_text": action.action_text,
                **outcome,
            },
        )
        template.last_triggered_at = reference_time
        template.last_triggered_event_id = event.id
        return event

    async def _idle_event(self, session: AsyncSession, *, world: SimulationWorld, tick_no: int, reference_time) -> SimulationEvent:
        return await self._create_event(
            session,
            world=world,
            tick_no=tick_no,
            reference_time=reference_time,
            event_type="world_idle",
            source="deterministic",
            actors=[],
            location_id=None,
            payload={
                "summary": "No active agents or random events were ready during this step.",
                "accepted": True,
                "state_changes": {},
                "observations": [],
                "memory_writes": [],
                "rule_effects": [],
                "needs_review": False,
                "raw_outcome": "",
            },
        )

    async def _create_event(
        self,
        session: AsyncSession,
        *,
        world: SimulationWorld,
        tick_no: int,
        reference_time,
        event_type: str,
        source: str,
        actors: list[str],
        location_id: str | None,
        payload: dict[str, Any],
    ) -> SimulationEvent:
        event = SimulationEvent(
            world_id=world.id,
            tick_no=tick_no,
            event_type=event_type,
            source=source,
            status="needs_review" if payload.get("needs_review") else "completed",
            reference_time=reference_time,
            actors=actors,
            location_id=location_id,
            payload={
                "world_id": world.id,
                "reference_time": reference_time.isoformat(),
                **payload,
            },
        )
        session.add(event)
        await session.flush()
        return event

    async def _persist_memory(self, session: AsyncSession, event: SimulationEvent) -> None:
        try:
            await self.memory_writer.persist_event(session, simulation_event=event)
        except Exception:
            await session.flush()

    async def _ensure_agent_state(self, session: AsyncSession, agent: SimAgent) -> AgentState:
        if agent.state is not None:
            return agent.state
        state = AgentState(agent_id=agent.id)
        session.add(state)
        await session.flush()
        agent.state = state
        return state

    async def _intended_action(
        self,
        session: AsyncSession,
        *,
        agent: SimAgent,
        observation: dict[str, Any],
        fallback_location: WorldLocation | None,
    ) -> tuple[str, str]:
        if self.settings.simulation_use_letta_actions and self.settings.llm_api_key and self.settings.llm_api_key != "replace-me":
            try:
                persona: Persona = agent.persona
                bundle = await self.context_builder.build(
                    session,
                    persona=persona,
                    query=str(observation),
                    counterparty_user_id=None,
                    conversation_id=None,
                )
                prompt = (
                    "Choose the next concrete simulation action for this persona. "
                    "Return one short third-person action sentence only.\n"
                    f"Observation: {observation}"
                )
                text = await self.letta.send_message(persona, prompt, bundle, recent_messages=[])
                if text.strip():
                    return text.strip().splitlines()[0][:1200], "letta"
            except Exception:
                pass
        location_name = fallback_location.name if fallback_location else "the current place"
        return f"{agent.name} goes to {location_name} and continues their routine while observing the town.", "deterministic"

    def _apply_outcome(self, *, agent: SimAgent, state: AgentState, outcome: dict[str, Any]) -> None:
        state.current_action = str(outcome.get("state_changes", {}).get("current_action") or state.current_action)
        if outcome.get("needs_review") or not outcome.get("accepted", True):
            return
        changes = outcome.get("state_changes") if isinstance(outcome.get("state_changes"), dict) else {}
        location_id = changes.get("current_location_id") or changes.get("location_id")
        if isinstance(location_id, str) and location_id:
            agent.current_location_id = location_id
        mood = changes.get("mood")
        if isinstance(mood, str) and mood:
            state.mood = mood[:80]
        needs = changes.get("needs")
        if isinstance(needs, dict):
            state.needs = needs
        current_action = changes.get("current_action")
        if isinstance(current_action, str) and current_action:
            state.current_action = current_action

    def _action_status(self, outcome: dict[str, Any]) -> str:
        if outcome.get("needs_review"):
            return "needs_review"
        return "completed" if outcome.get("accepted", True) else "rejected"

    def _select_agents(self, agents: list[SimAgent], rng: random.Random) -> list[SimAgent]:
        if not agents:
            return []
        count = max(1, min(self.settings.simulation_max_agents_per_step, len(agents)))
        return rng.sample(agents, count)

    def _choose_next_location(self, agent: SimAgent, locations: list[WorldLocation], rng: random.Random) -> WorldLocation | None:
        if not locations:
            return None
        alternatives = [location for location in locations if location.id != agent.current_location_id]
        return rng.choice(alternatives or locations)

    def _build_observation(
        self,
        *,
        world: SimulationWorld,
        agent: SimAgent,
        locations: list[WorldLocation],
        rules: list[CommunityRule],
        recent_events: list[SimulationEvent],
        interventions: list[UserIntervention],
        suggested_location: WorldLocation | None,
    ) -> dict[str, Any]:
        return {
            "world": self._world_context(world),
            "agent": {
                "id": agent.id,
                "name": agent.name,
                "persona_id": agent.persona_id,
                "status": agent.status,
                "current_location_id": agent.current_location_id,
                "home_location_id": agent.home_location_id,
                "goals": agent.goals,
                "traits": agent.traits,
            },
            "suggested_location_id": suggested_location.id if suggested_location else agent.current_location_id,
            "locations": self._locations_context(locations),
            "rules": self.rulebook.to_context(rules),
            "recent_events": self._events_context(recent_events),
            "interventions": self._interventions_context(interventions),
        }

    def _world_context(self, world: SimulationWorld) -> dict[str, Any]:
        return {
            "id": world.id,
            "name": world.name,
            "status": world.status,
            "clock_time": world.clock_time.isoformat(),
            "tick_no": world.tick_no,
            "settings": world.settings,
        }

    def _locations_context(self, locations: list[WorldLocation]) -> list[dict[str, Any]]:
        return [
            {
                "id": location.id,
                "name": location.name,
                "kind": location.kind,
                "x": location.x,
                "y": location.y,
                "description": location.description,
                "metadata": location.metadata_,
            }
            for location in locations
        ]

    def _events_context(self, events: list[SimulationEvent]) -> list[dict[str, Any]]:
        return [
            {
                "id": event.id,
                "tick_no": event.tick_no,
                "event_type": event.event_type,
                "reference_time": event.reference_time.isoformat(),
                "actors": event.actors,
                "summary": event.payload.get("summary"),
            }
            for event in events
        ]

    def _interventions_context(self, interventions: list[UserIntervention]) -> list[dict[str, Any]]:
        return [
            {
                "id": intervention.id,
                "actor": intervention.actor,
                "intervention_type": intervention.intervention_type,
                "payload": intervention.payload,
                "created_at": intervention.created_at.isoformat(),
            }
            for intervention in interventions
        ]

    async def _recent_events(self, session: AsyncSession, world_id: str) -> list[SimulationEvent]:
        return (
            await session.execute(
                select(SimulationEvent)
                .where(SimulationEvent.world_id == world_id)
                .order_by(desc(SimulationEvent.reference_time), desc(SimulationEvent.created_at))
                .limit(12)
            )
        ).scalars().all()

    async def _maybe_snapshot(self, session: AsyncSession, *, world: SimulationWorld, event_cursor: str | None) -> None:
        interval = self.settings.simulation_snapshot_interval
        if interval <= 0 or world.tick_no % interval != 0:
            return
        state = await self.projector.project(session, world.id)
        session.add(
            WorldSnapshot(
                world_id=world.id,
                tick_no=world.tick_no,
                clock_time=world.clock_time,
                state=state.model_dump(mode="json"),
                event_cursor=event_cursor,
            )
        )
