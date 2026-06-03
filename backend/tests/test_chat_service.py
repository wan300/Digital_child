import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.models.entities import Conversation, Message, Persona
from app.schemas.api import ChatMessageCreate, ContextBundle
from app.services import chat_service as chat_service_module
from app.services.chat_service import ChatService


@pytest.mark.asyncio
async def test_chat_service_commits_user_message_before_llm(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'chat.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with Session() as session:
        persona = Persona(id="p1", name="星尘", persona_block="你是星尘。", letta_agent_id="local-p1")
        conversation = Conversation(id="c1", persona_id="p1", counterparty_user_id="u1", title="test")
        session.add_all([persona, conversation])
        await session.commit()

    class FakeContextBuilder:
        async def build(self, session, *, persona, query, counterparty_user_id, conversation_id):  # noqa: ANN001
            return ContextBundle(core_persona=persona.persona_block, current_human_relationship="test")

    class FakeLettaClient:
        async def ensure_agent(self, persona):  # noqa: ANN001
            return f"local-{persona.id}"

        async def send_message(self, persona, user_message, context_bundle, recent_messages=None):  # noqa: ANN001
            async with Session() as check_session:
                row = (
                    await check_session.execute(
                        select(Message).where(
                            Message.conversation_id == "c1",
                            Message.role == "user",
                            Message.content == user_message,
                        )
                    )
                ).scalar_one_or_none()
            assert row is not None
            assert recent_messages == []
            return "这是模型生成的最终回复。"

    class FakeMemoryWriter:
        async def persist_turn(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
            return None

    monkeypatch.setattr(chat_service_module, "ContextBuilder", FakeContextBuilder)
    monkeypatch.setattr(chat_service_module, "LettaClient", FakeLettaClient)
    monkeypatch.setattr(chat_service_module, "MemoryWriter", FakeMemoryWriter)

    async with Session() as session:
        response = await ChatService().send_message(session, "c1", ChatMessageCreate(content="你好"))

    async with Session() as session:
        rows = (await session.execute(select(Message).where(Message.conversation_id == "c1"))).scalars().all()

    await engine.dispose()

    assert response.assistant_message.content == "这是模型生成的最终回复。"
    assert [(row.role, row.content) for row in rows] == [("user", "你好"), ("assistant", "这是模型生成的最终回复。")]
