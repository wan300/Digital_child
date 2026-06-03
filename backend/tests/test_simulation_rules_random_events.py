import random
from datetime import UTC, datetime, timedelta

from app.models.entities import CommunityRule, RandomEventTemplate
from app.simulation.random_events import RandomEventScheduler
from app.simulation.rulebook import Rulebook


def test_rulebook_active_rules_are_priority_ordered() -> None:
    now = datetime(2026, 6, 1, tzinfo=UTC)
    later = CommunityRule(title="later", content="later", priority=1, status="active", effective_from=now + timedelta(days=1))
    low = CommunityRule(title="low", content="low", priority=20, status="active", effective_from=None)
    high = CommunityRule(title="high", content="high", priority=5, status="active", effective_from=now - timedelta(days=1))
    disabled = CommunityRule(title="disabled", content="disabled", priority=0, status="disabled", effective_from=None)

    rules = Rulebook().active_rules([later, low, high, disabled], now=now)

    assert [rule.title for rule in rules] == ["high", "low"]
    assert [item["title"] for item in Rulebook().to_context(rules)] == ["high", "low"]


def test_random_event_probability_and_cooldown_are_deterministic() -> None:
    now = datetime(2026, 6, 1, tzinfo=UTC)
    template = RandomEventTemplate(
        name="rain",
        trigger={"min_tick": 2, "every_n_ticks": 2},
        probability=1.0,
        cooldown=60,
        severity="info",
        effect_prompt="It rains.",
        status="active",
    )
    scheduler = RandomEventScheduler()

    assert scheduler.due_templates([template], tick_no=1, clock_time=now, rng=random.Random("seed")) == []
    assert scheduler.due_templates([template], tick_no=2, clock_time=now, rng=random.Random("seed")) == [template]

    template.last_triggered_at = now
    assert scheduler.due_templates([template], tick_no=4, clock_time=now + timedelta(minutes=30), rng=random.Random("seed")) == []
    assert scheduler.due_templates([template], tick_no=6, clock_time=now + timedelta(minutes=60), rng=random.Random("seed")) == [template]
