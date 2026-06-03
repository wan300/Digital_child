from __future__ import annotations

import random
from datetime import datetime, timedelta

from app.models.entities import RandomEventTemplate


class RandomEventScheduler:
    def due_templates(
        self,
        templates: list[RandomEventTemplate],
        *,
        tick_no: int,
        clock_time: datetime,
        rng: random.Random,
    ) -> list[RandomEventTemplate]:
        due: list[RandomEventTemplate] = []
        for template in sorted(templates, key=lambda item: item.name):
            if template.status != "active":
                continue
            if not self._trigger_conditions_match(template, tick_no=tick_no):
                continue
            if not self._cooldown_elapsed(template, clock_time=clock_time):
                continue
            if rng.random() <= template.probability:
                due.append(template)
        return due

    def _trigger_conditions_match(self, template: RandomEventTemplate, *, tick_no: int) -> bool:
        trigger = template.trigger or {}
        min_tick = trigger.get("min_tick")
        if min_tick is not None and tick_no < int(min_tick):
            return False
        every_n_ticks = trigger.get("every_n_ticks")
        return not (every_n_ticks is not None and int(every_n_ticks) > 0 and tick_no % int(every_n_ticks) != 0)

    def _cooldown_elapsed(self, template: RandomEventTemplate, *, clock_time: datetime) -> bool:
        if template.last_triggered_at is None or template.cooldown <= 0:
            return True
        last_triggered_at = _align_timezone(template.last_triggered_at, clock_time)
        return clock_time - last_triggered_at >= timedelta(minutes=template.cooldown)


def _align_timezone(value: datetime, reference: datetime) -> datetime:
    if value.tzinfo is None and reference.tzinfo is not None:
        return value.replace(tzinfo=reference.tzinfo)
    if value.tzinfo is not None and reference.tzinfo is None:
        return value.replace(tzinfo=None)
    return value
