import pytest

from app.simulation.concordia_adapter import ConcordiaAdapter
from app.simulation.deepseek_concordia_model import DEEPSEEK_REASONING_EFFORT, DeepSeekGptLanguageModel


@pytest.mark.asyncio
async def test_concordia_adapter_valid_json(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeModel:
        def sample_text(self, *_args, **_kwargs):  # noqa: ANN002, ANN003
            return (
                '{"accepted": true, "summary": "ok", "state_changes": {"current_action": "walk"}, '
                '"observations": [], "memory_writes": [], "rule_effects": [], '
                '"needs_review": false, "raw_outcome": ""}'
            )

    adapter = ConcordiaAdapter()
    monkeypatch.setattr(adapter, "_get_model", lambda: FakeModel())

    outcome = await adapter.resolve_action(context={"agent": {"id": "a1"}}, action_text="walk")

    assert outcome["accepted"] is True
    assert outcome["summary"] == "ok"
    assert outcome["state_changes"]["current_action"] == "walk"
    assert outcome["needs_review"] is False


@pytest.mark.asyncio
async def test_concordia_adapter_invalid_json_needs_review(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeModel:
        def sample_text(self, *_args, **_kwargs):  # noqa: ANN002, ANN003
            return "not json"

    adapter = ConcordiaAdapter()
    monkeypatch.setattr(adapter, "_get_model", lambda: FakeModel())

    outcome = await adapter.resolve_action(context={}, action_text="impossible action")

    assert outcome["accepted"] is False
    assert outcome["needs_review"] is True
    assert outcome["raw_outcome"] == "not json"


@pytest.mark.asyncio
async def test_concordia_adapter_salvages_partial_json(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeModel:
        def sample_text(self, *_args, **_kwargs):  # noqa: ANN002, ANN003
            return (
                '{"accepted": true, "summary": "远程摘要", "half_day_summary": "远程半天摘要", '
                '"child_interpretation": "我玩了一会儿。", '
                '"gm_interpretation": "远程 GM 解释", '
                '"observed_facts": ["事实一"], '
                '"suggested_updates": {"development_evidence": ['
            )

    adapter = ConcordiaAdapter()
    monkeypatch.setattr(adapter, "_get_model", lambda: FakeModel())

    outcome = await adapter.resolve_action(context={}, action_text="play")

    assert outcome["gm_source"] == "concordia_wrapper_partial"
    assert outcome["needs_review"] is True
    assert outcome["half_day_summary"] == "远程半天摘要"
    assert outcome["gm_interpretation"] == "远程 GM 解释"
    assert outcome["observed_facts"] == ["事实一"]


@pytest.mark.asyncio
async def test_concordia_adapter_wrapper_error_uses_direct_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    class BrokenModel:
        def sample_text(self, *_args, **_kwargs):  # noqa: ANN002, ANN003
            raise RuntimeError("provider rejected wrapper params")

    async def fake_direct_llm(*, prompt: str, response_format: bool) -> str:  # noqa: ARG001
        return (
            '{"accepted": true, "summary": "remote gm ok", "state_changes": {"current_action": "play"}, '
            '"observations": [], "memory_writes": [], "rule_effects": [], '
            '"needs_review": false, "raw_outcome": ""}'
        )

    adapter = ConcordiaAdapter()
    monkeypatch.setattr(adapter, "_get_model", lambda: BrokenModel())
    monkeypatch.setattr(adapter.settings, "llm_api_key", "test-key")
    monkeypatch.setattr(adapter, "_request_direct_llm", fake_direct_llm)

    outcome = await adapter.resolve_action(context={"agent": {"id": "a1"}}, action_text="play")

    assert outcome["summary"] == "remote gm ok"
    assert outcome["gm_source"] == "direct_openai_compatible"
    assert outcome["concordia_wrapper_error"] == "RuntimeError"


def test_deepseek_concordia_model_uses_xhigh_for_sample_text(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict] = []

    class FakeMessage:
        content = '{"accepted": true}'

    class FakeChoice:
        message = FakeMessage()

    class FakeResponse:
        choices = [FakeChoice()]

    class FakeCompletions:
        def create(self, **kwargs):  # noqa: ANN003
            calls.append(kwargs)
            return FakeResponse()

    class FakeChat:
        completions = FakeCompletions()

    class FakeOpenAI:
        chat = FakeChat()

        def __init__(self, **_kwargs):  # noqa: ANN003
            pass

    monkeypatch.setattr("app.simulation.deepseek_concordia_model.openai.OpenAI", FakeOpenAI)

    model = DeepSeekGptLanguageModel(model_name="deepseek-v4-pro", api_key="test-key", api_base="https://api.deepseek.com")
    assert model.sample_text("return json", max_tokens=32) == '{"accepted": true}'

    assert calls[0]["reasoning_effort"] == DEEPSEEK_REASONING_EFFORT
    assert calls[0]["max_completion_tokens"] == 32


def test_deepseek_concordia_model_keeps_sample_choice_medium(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict] = []

    class FakeMessage:
        content = "yes"

    class FakeChoice:
        message = FakeMessage()

    class FakeResponse:
        choices = [FakeChoice()]

    class FakeCompletions:
        def create(self, **kwargs):  # noqa: ANN003
            calls.append(kwargs)
            return FakeResponse()

    class FakeChat:
        completions = FakeCompletions()

    class FakeOpenAI:
        chat = FakeChat()

        def __init__(self, **_kwargs):  # noqa: ANN003
            pass

    monkeypatch.setattr("app.simulation.deepseek_concordia_model.openai.OpenAI", FakeOpenAI)

    model = DeepSeekGptLanguageModel(model_name="deepseek-v4-pro", api_key="test-key", api_base="https://api.deepseek.com")
    index, choice, _debug = model.sample_choice("choose", ["yes", "no"])

    assert index == 0
    assert choice == "yes"
    assert calls[0]["reasoning_effort"] == "medium"


def test_concordia_adapter_selects_deepseek_wrapper(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeOpenAI:
        def __init__(self, **_kwargs):  # noqa: ANN003
            pass

    adapter = ConcordiaAdapter()
    monkeypatch.setattr(adapter.settings, "chat_model", "deepseek-v4-pro")
    monkeypatch.setattr(adapter.settings, "llm_base_url", "https://api.deepseek.com")
    monkeypatch.setattr(adapter.settings, "llm_api_key", "test-key")
    monkeypatch.setattr("app.simulation.deepseek_concordia_model.openai.OpenAI", FakeOpenAI)

    model = adapter._get_model()

    assert isinstance(model, DeepSeekGptLanguageModel)
    assert adapter._concordia_max_tokens() >= 8192


@pytest.mark.asyncio
async def test_concordia_adapter_unavailable_deterministic_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = ConcordiaAdapter()
    monkeypatch.setattr(adapter, "_get_model", lambda: None)
    monkeypatch.setattr(adapter.settings, "llm_api_key", "")

    outcome = await adapter.resolve_action(
        context={
            "agent": {"id": "a1", "name": "Ada", "current_location_id": "l1"},
            "suggested_location_id": "l2",
        },
        action_text="Ada walks to the square.",
    )

    assert outcome["accepted"] is True
    assert outcome["needs_review"] is False
    assert outcome["state_changes"]["agent_id"] == "a1"
    assert outcome["state_changes"]["current_location_id"] == "l2"
    assert outcome["fallback_reason"] == "concordia_unavailable"
