from __future__ import annotations

from datetime import datetime

from app.models.entities import CommunityRule


class Rulebook:
    def active_rules(self, rules: list[CommunityRule], *, now: datetime) -> list[CommunityRule]:
        return sorted(
            [
                rule
                for rule in rules
                if rule.status == "active" and (rule.effective_from is None or _align_timezone(rule.effective_from, now) <= now)
            ],
            key=lambda rule: (rule.priority, rule.created_at),
        )

    def to_context(self, rules: list[CommunityRule]) -> list[dict[str, object]]:
        return [
            {
                "id": rule.id,
                "title": rule.title,
                "content": rule.content,
                "priority": rule.priority,
                "metadata": rule.metadata_,
            }
            for rule in rules
        ]


def _align_timezone(value: datetime, reference: datetime) -> datetime:
    if value.tzinfo is None and reference.tzinfo is not None:
        return value.replace(tzinfo=reference.tzinfo)
    if value.tzinfo is not None and reference.tzinfo is None:
        return value.replace(tzinfo=None)
    return value
