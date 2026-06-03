from types import SimpleNamespace

import pytest

from app.clients.letta_client import LettaClient
from app.models.entities import Message, Persona
from app.schemas.api import ContextBundle, EvidenceItem


@pytest.mark.asyncio
async def test_local_agent_uses_direct_llm_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    posts = []

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"choices": [{"message": {"content": "这是模型生成的最终回复。"}}]}

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
            return None

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args) -> None:  # noqa: ANN002
            return None

        async def post(self, url: str, headers: dict, json: dict) -> FakeResponse:  # noqa: A002
            posts.append({"url": url, "headers": headers, "json": json})
            return FakeResponse()

    monkeypatch.setattr("app.clients.letta_client.httpx.AsyncClient", FakeAsyncClient)
    client = LettaClient()
    client.settings = SimpleNamespace(
        llm_api_key="test-key",
        llm_base_url="https://llm.example/v1",
        chat_model="chat-model",
        letta_api_key="",
        letta_server_password="",
    )
    persona = Persona(
        id="p1",
        name="星尘",
        persona_block="你是星尘，一位图书馆管理员。",
        letta_agent_id="local-p1",
    )
    context = ContextBundle(
        core_persona="图书馆管理员",
        current_human_relationship="验收用户",
        long_term_memories=[EvidenceItem(source="local", content="星尘擅长整理知识线索。")],
    )

    recent_messages = [
        Message(conversation_id="c1", role="user", content="上一轮问题", context={}),
        Message(conversation_id="c1", role="assistant", content="上一轮回答", context={}),
    ]

    answer = await client.send_message(persona, "你好", context, recent_messages=recent_messages)

    assert answer == "这是模型生成的最终回复。"
    assert len(posts) == 1
    assert posts[0]["url"] == "https://llm.example/v1/chat/completions"
    assert posts[0]["json"]["model"] == "chat-model"
    assert "星尘擅长整理知识线索" in posts[0]["json"]["messages"][1]["content"]
    assert "上一轮问题" in posts[0]["json"]["messages"][1]["content"]
    assert "上一轮回答" in posts[0]["json"]["messages"][1]["content"]
