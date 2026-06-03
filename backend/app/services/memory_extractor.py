from __future__ import annotations

import re

from app.schemas.api import MemoryCandidate
from app.services.privacy_filter import PrivacyFilter


class MemoryExtractor:
    def __init__(self) -> None:
        self.privacy_filter = PrivacyFilter()

    def extract_from_turn(self, *, persona_id: str, counterparty_user_id: str, user_text: str, assistant_text: str, source_event_id: str) -> list[MemoryCandidate]:
        candidates: list[MemoryCandidate] = []
        text = user_text.strip()
        patterns = [
            (r"请记住[:：]?\s*(.+)", "fact", 0.9),
            (r"我喜欢(.+)", "preference", 0.78),
            (r"我不喜欢(.+)", "preference", 0.78),
            (r"我希望(.+)", "goal", 0.72),
            (r"以后(.+)", "preference", 0.68),
            (r"I prefer (.+)", "preference", 0.78),
            (r"remember that (.+)", "fact", 0.9),
        ]
        for pattern, memory_type, confidence in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if not match:
                continue
            content = match.group(1).strip(" 。.，,")
            if not content:
                continue
            candidate = MemoryCandidate(
                content=f"当前用户表达：{content}",
                subject=f"human:{counterparty_user_id}",
                memory_type=memory_type,
                confidence=confidence,
                source_event_id=source_event_id,
                decision="approved",
                metadata={"persona_id": persona_id, "counterparty_user_id": counterparty_user_id},
            )
            candidates.append(self.privacy_filter.filter_candidate(candidate))

        if "我叫" in text:
            name = text.split("我叫", 1)[1].strip(" 。.，,")
            if name:
                candidates.append(
                    self.privacy_filter.filter_candidate(
                        MemoryCandidate(
                            content=f"当前用户自称 {name}",
                            subject=f"human:{counterparty_user_id}",
                            memory_type="identity",
                            confidence=0.82,
                            source_event_id=source_event_id,
                            decision="approved",
                            metadata={"persona_id": persona_id, "counterparty_user_id": counterparty_user_id},
                        )
                    )
                )
        return candidates
