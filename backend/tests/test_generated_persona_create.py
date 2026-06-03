import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.routes import personas as persona_routes
from app.db.base import Base
from app.models.entities import MemoryRecord
from app.schemas.api import GeneratedMemoryDraft, GeneratedPersonaCreate
from app.services.context_builder import ContextBuilder


@pytest.mark.asyncio
async def test_generated_persona_create_forces_fictional_and_persona_memories(monkeypatch: pytest.MonkeyPatch) -> None:
    mem0_calls = []

    class FakeMem0Client:
        async def add(self, messages, *, user_id, agent_id, run_id, metadata):  # noqa: ANN001
            mem0_calls.append(
                {"messages": messages, "user_id": user_id, "agent_id": agent_id, "run_id": run_id, "metadata": metadata}
            )
            return "mem0-id"

    class FakeGraphitiClient:
        def group_id(self, persona_id: str, counterparty_user_id: str | None = None) -> str:
            return f"persona:{persona_id}:global"

        async def add_episode(self, **kwargs):  # noqa: ANN003
            return "episode-id"

    monkeypatch.setattr(persona_routes, "Mem0Client", FakeMem0Client)
    monkeypatch.setattr(persona_routes, "GraphitiClient", FakeGraphitiClient)

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with Session() as session:
        persona = await persona_routes.create_generated_persona(
            GeneratedPersonaCreate(
                name="Generated",
                description="Generated description",
                persona_block="Generated persona block",
                human_block="Unknown user relationship",
                memories=[
                    GeneratedMemoryDraft(content="Generated once worked in an old bookstore.", memory_type="event"),
                    GeneratedMemoryDraft(content="Generated has an api key secret-token.", memory_type="fact"),
                ],
            ),
            session,
        )

        records = (
            await session.execute(select(MemoryRecord).where(MemoryRecord.persona_id == persona.id).order_by(MemoryRecord.content))
        ).scalars().all()
        recalled = await ContextBuilder()._local_memories(session, persona.id, None, "old bookstore")

    await engine.dispose()

    assert persona.persona_type == "fictional_persona"
    assert {record.subject for record in records} == {f"persona:{persona.id}"}
    assert {record.scope for record in records} == {"persona"}
    assert len(mem0_calls) == 1
    assert any(record.decision == "approved" and record.external_id == "mem0-id" for record in records)
    assert any(record.decision == "pending" and record.external_id is None for record in records)
    assert any("old bookstore" in item.content for item in recalled)
