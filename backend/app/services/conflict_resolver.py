from __future__ import annotations

from app.schemas.api import ConflictNote, EvidenceItem


class ConflictResolver:
    contradiction_markers = (
        ("喜欢", "不喜欢"),
        ("愿意", "不愿意"),
        ("经常", "很少"),
        ("always", "never"),
        ("likes", "dislikes"),
    )

    def resolve(self, evidence: list[EvidenceItem]) -> list[ConflictNote]:
        notes: list[ConflictNote] = []
        for positive, negative in self.contradiction_markers:
            positive_items = [item for item in evidence if positive in item.content]
            negative_items = [item for item in evidence if negative in item.content]
            if positive_items and negative_items:
                notes.append(
                    ConflictNote(
                        claim=f"{positive}/{negative}",
                        status="conflicted",
                        current_best_view="存在前后或来源冲突。回答时应说明时间、来源和当前最可靠判断，不要直接覆盖旧事实。",
                        supporting_evidence=[*positive_items[:2], *negative_items[:2]],
                    )
                )
        return notes
