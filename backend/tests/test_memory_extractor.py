from app.services.memory_extractor import MemoryExtractor


def test_memory_extractor_creates_human_preference_candidate() -> None:
    candidates = MemoryExtractor().extract_from_turn(
        persona_id="p1",
        counterparty_user_id="u1",
        user_text="请记住：我喜欢简洁直接的回答。",
        assistant_text="我会记住。",
        source_event_id="evt1",
    )
    assert candidates
    assert candidates[0].subject == "human:u1"
    assert candidates[0].decision == "approved"
