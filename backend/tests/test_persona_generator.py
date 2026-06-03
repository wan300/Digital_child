import json

import pytest

from app.services.persona_generator import PersonaGenerationError, PersonaGenerator


def test_persona_generator_parses_valid_json() -> None:
    payload = {
        "name": "林晚舟",
        "description": "一位虚构的城市档案整理员。",
        "persona_block": "林晚舟说话克制、温和，重视事实边界。",
        "human_block": "尚未形成稳定关系摘要。",
        "memories": [
            {"content": "林晚舟曾在旧书店整理地方志。", "memory_type": "event", "confidence": 0.82},
            {"content": "林晚舟偏好先给结论再解释依据。", "memory_type": "preference", "confidence": 0.76},
        ],
    }

    draft = PersonaGenerator()._parse_response(json.dumps(payload, ensure_ascii=False), memory_count=8)

    assert draft.name == "林晚舟"
    assert len(draft.memories) == 2
    assert draft.memories[0].memory_type == "event"


def test_persona_generator_rejects_invalid_json() -> None:
    with pytest.raises(PersonaGenerationError, match="invalid JSON"):
        PersonaGenerator()._parse_response("not json", memory_count=8)


def test_persona_generator_rejects_missing_fields() -> None:
    with pytest.raises(PersonaGenerationError, match="missing required fields"):
        PersonaGenerator()._parse_response(json.dumps({"name": "No memories"}), memory_count=8)


def test_persona_generator_validates_required_description_terms() -> None:
    generator = PersonaGenerator()
    terms = generator._required_terms("一个虚构的图书馆夜班管理员，擅长整理知识。")
    draft = generator._parse_response(
        json.dumps(
            {
                "name": "陈墨",
                "description": "陈墨是图书馆夜班管理员。",
                "persona_block": "他擅长整理知识，回答温和准确。",
                "human_block": "尚未形成稳定关系摘要。",
                "memories": [{"content": "陈墨常在夜班整理书架。", "memory_type": "event", "confidence": 0.8}],
            },
            ensure_ascii=False,
        ),
        memory_count=4,
    )

    generator._validate_alignment(draft, terms)

    bad_draft = draft.model_copy(update={"description": "陈墨是平面设计师。", "persona_block": "他喜欢视觉表达。"})
    with pytest.raises(PersonaGenerationError, match="did not match description"):
        generator._validate_alignment(bad_draft, terms)
