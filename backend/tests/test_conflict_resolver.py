from app.schemas.api import EvidenceItem
from app.services.conflict_resolver import ConflictResolver


def test_conflict_resolver_flags_opposite_preferences() -> None:
    notes = ConflictResolver().resolve(
        [
            EvidenceItem(source="mem0", content="Alice 喜欢公开演讲。"),
            EvidenceItem(source="graphiti", content="Alice 现在不喜欢大型公开活动。"),
        ]
    )
    assert notes
    assert notes[0].status == "conflicted"
