from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.models.entities import (
    Event,
    GraphEpisodeLink,
    MemoryRecord,
    Persona,
    SimAgent,
    SimulationEvent,
    SimulationWorld,
)
from app.simulation import memory_writer as memory_writer_module
from app.simulation.memory_writer import SimulationMemoryWriter


@pytest.mark.asyncio
async def test_simulation_memory_writer_persists_local_event_graph_link_and_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeGraphitiClient:
        def group_id(self, persona_id: str, counterparty_user_id: str | None = None) -> str:
            return f"persona:{persona_id}:global"

        async def add_episode(self, **_kwargs):  # noqa: ANN003
            return "episode-id"

    class FakeMem0Client:
        async def add(self, *_args, **_kwargs):  # noqa: ANN002, ANN003
            return "mem0-id"

    monkeypatch.setattr(memory_writer_module, "GraphitiClient", FakeGraphitiClient)
    monkeypatch.setattr(memory_writer_module, "Mem0Client", FakeMem0Client)

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with Session() as session:
        session.add_all(
            [
                SimulationWorld(id="w1", name="Town"),
                Persona(id="p1", name="Ada", persona_block="Ada"),
                SimAgent(id="a1", world_id="w1", persona_id="p1", name="Ada"),
            ]
        )
        await session.flush()
        simulation_event = SimulationEvent(
            id="se1",
            world_id="w1",
            tick_no=1,
            event_type="agent_action",
            source="deterministic",
            status="completed",
            reference_time=datetime(2026, 6, 1, tzinfo=UTC),
            actors=["a1"],
            payload={
                "summary": "Ada helped at the library.",
                "memory_writes": [{"agent_id": "a1", "content": "Ada helped at the library.", "memory_type": "event"}],
            },
        )
        session.add(simulation_event)
        await session.flush()
        await SimulationMemoryWriter().persist_event(session, simulation_event=simulation_event)
        await session.commit()

        events = (await session.execute(select(Event))).scalars().all()
        links = (await session.execute(select(GraphEpisodeLink))).scalars().all()
        memories = (await session.execute(select(MemoryRecord))).scalars().all()

    await engine.dispose()

    assert len(events) == 1
    assert events[0].payload["world_id"] == "w1"
    assert events[0].payload["simulation_event_id"] == "se1"
    assert len(links) == 1
    assert links[0].graph_episode_uuid == "episode-id"
    assert len(memories) == 1
    assert memories[0].external_id == "mem0-id"
    assert memories[0].metadata_["simulation_event_id"] == "se1"
