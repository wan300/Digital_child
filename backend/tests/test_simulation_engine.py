from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.models.entities import (
    AgentState,
    CommunityRule,
    Persona,
    RandomEventTemplate,
    SimAgent,
    SimulationEvent,
    SimulationWorld,
    WorldLocation,
    WorldSnapshot,
)
from app.simulation.engine import SimulationEngine


@pytest.mark.asyncio
async def test_simulation_engine_steps_text_world_with_fallback(tmp_path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'simulation.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with Session() as session:
        world = SimulationWorld(
            id="w1",
            name="Test Town",
            status="paused",
            clock_time=datetime(2026, 6, 1, 8, 0, tzinfo=UTC),
            seed=7,
        )
        home = WorldLocation(id="l1", world_id="w1", name="Home", kind="home", x=0, y=0)
        square = WorldLocation(id="l2", world_id="w1", name="Square", kind="public", x=10, y=10)
        persona_a = Persona(id="p1", name="Ada", persona_block="Ada is practical.")
        persona_b = Persona(id="p2", name="Bo", persona_block="Bo is curious.")
        agent_a = SimAgent(id="a1", world_id="w1", persona_id="p1", name="Ada", home_location_id="l1", current_location_id="l1")
        agent_b = SimAgent(id="a2", world_id="w1", persona_id="p2", name="Bo", home_location_id="l2", current_location_id="l2")
        session.add_all(
            [
                world,
                home,
                square,
                persona_a,
                persona_b,
                agent_a,
                agent_b,
                AgentState(agent_id="a1"),
                AgentState(agent_id="a2"),
                CommunityRule(world_id="w1", title="Be civil", content="Residents should be civil.", priority=1),
                RandomEventTemplate(
                    world_id="w1",
                    name="Market bell",
                    trigger={"min_tick": 2, "every_n_ticks": 2},
                    probability=1.0,
                    cooldown=60,
                    severity="info",
                    effect_prompt="The market bell rings across town.",
                ),
            ]
        )
        await session.commit()

        sim_engine = SimulationEngine()
        for _ in range(20):
            response = await sim_engine.step(session, "w1")
            await session.commit()

        events = (await session.execute(select(SimulationEvent).where(SimulationEvent.world_id == "w1"))).scalars().all()
        snapshots = (await session.execute(select(WorldSnapshot).where(WorldSnapshot.world_id == "w1"))).scalars().all()
        refreshed_world = await session.get(SimulationWorld, "w1")

    await engine.dispose()

    assert refreshed_world is not None
    assert refreshed_world.tick_no == 20
    assert len(events) >= 20
    assert any(event.event_type == "agent_action" for event in events)
    assert any(event.event_type == "random_event" for event in events)
    assert len(snapshots) == 4
    assert response.world.tick_no == 20
    assert response.state.agents
    assert all(event.status in {"completed", "needs_review"} for event in events)


@pytest.mark.asyncio
async def test_simulation_engine_preserves_needs_review_raw_outcome(tmp_path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'needs_review.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    class FakeAdapter:
        async def resolve_action(self, *, context, action_text):  # noqa: ANN001
            return {
                "accepted": False,
                "summary": "needs review",
                "state_changes": {"current_location_id": "l2", "current_action": "blocked"},
                "observations": [],
                "memory_writes": [],
                "rule_effects": [],
                "needs_review": True,
                "raw_outcome": "not-json",
            }

    async with Session() as session:
        session.add_all(
            [
                SimulationWorld(id="w1", name="Town", clock_time=datetime(2026, 6, 1, 8, 0, tzinfo=UTC)),
                WorldLocation(id="l1", world_id="w1", name="Home"),
                WorldLocation(id="l2", world_id="w1", name="Square"),
                Persona(id="p1", name="Ada", persona_block="Ada"),
                SimAgent(id="a1", world_id="w1", persona_id="p1", name="Ada", current_location_id="l1"),
                AgentState(agent_id="a1"),
            ]
        )
        await session.commit()

        sim_engine = SimulationEngine()
        sim_engine.adapter = FakeAdapter()
        await sim_engine.step(session, "w1")
        await session.commit()

        event = (await session.execute(select(SimulationEvent))).scalar_one()
        agent = await session.get(SimAgent, "a1")

    await engine.dispose()

    assert event.status == "needs_review"
    assert event.payload["raw_outcome"] == "not-json"
    assert agent is not None
    assert agent.current_location_id == "l1"
