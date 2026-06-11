from __future__ import annotations

import json
from typing import Any

OUTCOME_SCHEMA_KEYS = (
    "accepted",
    "summary",
    "main_action",
    "sub_fragments",
    "observed_facts",
    "child_interpretation",
    "gm_interpretation",
    "state_update_evidence",
    "half_day_summary",
    "life_slice",
    "suggested_updates",
    "risk_flags",
    "state_changes",
    "observations",
    "memory_writes",
    "rule_effects",
    "needs_review",
    "raw_outcome",
)


def build_resolution_prompt(context: dict[str, Any], action_text: str) -> str:
    return (
        "You are the game master for a persistent small-town social simulation.\n"
        "Judge whether the proposed action is plausible under the world state, locations, active rules, recent events, and user interventions.\n"
        "If world.type is child_growth_v1, the proposed action is a natural-language half-day routine for one fictional child, "
        "not a command-line action. Accept ordinary age-appropriate family, kindergarten, and community routines unless they "
        "violate child-safety constraints. For child_growth_v1, write user-visible summaries, child_interpretation, "
        "gm_interpretation, observed_facts, and evidence in Simplified Chinese.\n"
        "For child_growth_v1, never directly set development scores or rewrite the whole child state; provide evidence and "
        "suggested_updates only, because the backend rules clamp final needs, development, and relationships.\n"
        "Keep JSON concise except life_slice.dialogue: at most 3 sub_fragments, 4 observed_facts, 4 state_update_evidence entries, "
        "3 development_evidence items, 3 relationship_evidence items, and 2 memory_writes. "
        "Each string should be one short sentence unless the field explicitly asks for a 1-3 sentence summary.\n"
        "For child_growth_v1, include life_slice as a concrete half-day scene centered on the child: "
        "one scene_description and 10-20 age-appropriate dialogue turns. Use caregiver display labels from context, "
        "such as 爸爸 or 妈妈, instead of generic labels like 照护者. Do not mention metrics, scores, or GM reasoning in life_slice.\n"
        "Return only one valid JSON object with these keys: "
        f"{', '.join(OUTCOME_SCHEMA_KEYS)}.\n"
        "Use this JSON shape exactly:\n"
        "{\n"
        '  "accepted": true,\n'
        '  "summary": "short user-visible result",\n'
        '  "main_action": "one main half-day action if this is a child growth world",\n'
        '  "sub_fragments": ["optional child-safe fragment"],\n'
        '  "observed_facts": ["objective third-person fact"],\n'
        '  "child_interpretation": "one first-person sentence in child language",\n'
        '  "gm_interpretation": "GM explanation of meaning and recovery path",\n'
        '  "state_update_evidence": [{"field": "needs.energy", "reason": "observable evidence"}],\n'
        '  "half_day_summary": "1-3 sentence half-day summary",\n'
        '  "life_slice": {"scene_description": "brief concrete scene", "dialogue": [{"speaker": "child or participant display label", "text": "spoken line"}]},\n'
        '  "suggested_updates": {"development_evidence": [], "relationship_evidence": []},\n'
        '  "risk_flags": [],\n'
        '  "state_changes": {"agent_id": "...", "current_location_id": "...", "current_action": "..."},\n'
        '  "observations": [{"agent_id": "...", "text": "..."}],\n'
        '  "memory_writes": [{"agent_id": "...", "content": "...", "memory_type": "event", "confidence": 0.7}],\n'
        '  "rule_effects": [{"rule_id": "...", "effect": "..."}],\n'
        '  "needs_review": false,\n'
        '  "raw_outcome": ""\n'
        "}\n\n"
        "World context JSON:\n"
        f"{json.dumps(context, ensure_ascii=False, default=str)}\n\n"
        "Proposed action:\n"
        f"{action_text}"
    )
