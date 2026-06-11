from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx

from app.core.config import get_settings
from app.simulation.prompts import OUTCOME_SCHEMA_KEYS, build_resolution_prompt

DIRECT_LLM_MIN_MAX_TOKENS = 8192
DIRECT_LLM_TIMEOUT_SECONDS = 20
DEEPSEEK_CONCORDIA_MIN_MAX_TOKENS = 8192


class ConcordiaAdapter:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._model: Any | None = None
        self._init_attempted = False

    async def resolve_action(self, *, context: dict[str, Any], action_text: str) -> dict[str, Any]:
        try:
            return await asyncio.wait_for(
                self._resolve_action(context=context, action_text=action_text),
                timeout=max(1.0, float(self.settings.simulation_external_gm_timeout_seconds)),
            )
        except TimeoutError:
            return self._fallback_outcome(context=context, action_text=action_text, reason="external_gm_timeout")

    async def _resolve_action(self, *, context: dict[str, Any], action_text: str) -> dict[str, Any]:
        model = self._get_model()
        prompt = build_resolution_prompt(context, action_text)

        if model is not None:
            try:
                raw = await asyncio.to_thread(
                    model.sample_text,
                    prompt,
                    max_tokens=self._concordia_max_tokens(),
                    temperature=1.0,
                    timeout=min(
                        max(1.0, float(self.settings.simulation_direct_llm_timeout_seconds)),
                        max(1.0, float(self.settings.simulation_external_gm_timeout_seconds)),
                    ),
                )
                return self._normalize_raw_text(raw, source="concordia_wrapper")
            except Exception as exc:
                direct = await self._direct_llm_outcome(prompt=prompt)
                if direct is not None:
                    direct["concordia_wrapper_error"] = type(exc).__name__
                    return direct
                return self._fallback_outcome(context=context, action_text=action_text, reason=f"concordia_error:{type(exc).__name__}")

        direct = await self._direct_llm_outcome(prompt=prompt)
        if direct is not None:
            return direct
        return self._fallback_outcome(context=context, action_text=action_text, reason="concordia_unavailable")

    def _normalize_raw_text(self, raw: str, *, source: str) -> dict[str, Any]:
        parsed = self._parse_json_object(raw)
        if parsed is None:
            parsed = self._salvage_partial_outcome(raw)
            if parsed is not None:
                normalized = self._normalize_outcome(parsed, raw_outcome=raw)
                normalized["gm_source"] = f"{source}_partial"
                normalized["needs_review"] = True
                normalized["raw_outcome"] = raw
                return normalized
            return self._needs_review_outcome(raw)
        normalized = self._normalize_outcome(parsed, raw_outcome=raw)
        normalized["gm_source"] = source
        return normalized

    def _get_model(self) -> Any | None:
        if self._init_attempted:
            return self._model
        self._init_attempted = True
        if not self.settings.simulation_concordia_enabled:
            return None
        if not self.settings.llm_api_key or self.settings.llm_api_key == "replace-me":
            return None
        try:
            if self._is_deepseek_config():
                from app.simulation.deepseek_concordia_model import DeepSeekGptLanguageModel

                self._model = DeepSeekGptLanguageModel(
                    model_name=self.settings.chat_model,
                    api_key=self.settings.llm_api_key,
                    api_base=self.settings.llm_base_url,
                )
                return self._model

            from concordia.contrib.language_models.openai import gpt_model

            self._model = gpt_model.GptLanguageModel(
                model_name=self.settings.chat_model,
                api_key=self.settings.llm_api_key,
                api_base=self.settings.llm_base_url,
            )
        except Exception:
            self._model = None
        return self._model

    def _is_deepseek_config(self) -> bool:
        model = (self.settings.chat_model or "").lower()
        base_url = (self.settings.llm_base_url or "").lower()
        return "deepseek" in model or "deepseek" in base_url

    def _concordia_max_tokens(self) -> int:
        if self._is_deepseek_config():
            return max(self.settings.simulation_concordia_max_tokens, DEEPSEEK_CONCORDIA_MIN_MAX_TOKENS)
        return self.settings.simulation_concordia_max_tokens

    async def _direct_llm_outcome(self, *, prompt: str) -> dict[str, Any] | None:
        if not self.settings.llm_api_key or self.settings.llm_api_key == "replace-me":
            return None
        try:
            raw = await self._request_direct_llm(prompt=prompt, response_format=True)
        except httpx.HTTPStatusError as exc:
            # Some OpenAI-compatible providers do not support response_format.
            if exc.response.status_code not in {400, 422}:
                return None
            try:
                raw = await self._request_direct_llm(prompt=prompt, response_format=False)
            except Exception:
                return None
        except Exception:
            return None
        outcome = self._normalize_raw_text(raw, source="direct_openai_compatible")
        return outcome

    async def _request_direct_llm(self, *, prompt: str, response_format: bool) -> str:
        body: dict[str, Any] = {
            "model": self.settings.chat_model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a strict JSON-only game master. Return exactly one valid JSON object. "
                        "Do not include markdown, prose, or diagnostic text outside the JSON object."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "max_tokens": max(self.settings.simulation_concordia_max_tokens, DIRECT_LLM_MIN_MAX_TOKENS),
            "temperature": 0.7,
        }
        if response_format:
            body["response_format"] = {"type": "json_object"}
        timeout = max(1.0, float(getattr(self.settings, "simulation_direct_llm_timeout_seconds", DIRECT_LLM_TIMEOUT_SECONDS)))
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                f"{self.settings.llm_base_url.rstrip('/')}/chat/completions",
                headers=self._llm_headers(),
                json=body,
            )
            response.raise_for_status()
            data = response.json()
        return self._extract_message_content(data)

    def _llm_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.settings.llm_api_key}", "Content-Type": "application/json"}

    def _extract_message_content(self, data: dict[str, Any]) -> str:
        choices = data.get("choices") if isinstance(data.get("choices"), list) else []
        if not choices:
            raise ValueError("LLM response did not include choices")
        first = choices[0] if isinstance(choices[0], dict) else {}
        message = first.get("message") if isinstance(first.get("message"), dict) else {}
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            return content
        raise ValueError("LLM response did not include message content")

    def _parse_json_object(self, raw: str) -> dict[str, Any] | None:
        text = (raw or "").strip()
        if not text:
            return None
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}")
            if start < 0 or end <= start:
                return None
            try:
                data = json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                return None
        return data if isinstance(data, dict) else None

    def _salvage_partial_outcome(self, raw: str) -> dict[str, Any] | None:
        text = (raw or "").strip()
        if not text:
            return None
        salvaged: dict[str, Any] = {
            "accepted": True,
            "state_changes": {},
            "observations": [],
            "memory_writes": [],
            "rule_effects": [],
            "risk_flags": [],
            "needs_review": True,
            "raw_outcome": raw,
        }
        for key in OUTCOME_SCHEMA_KEYS:
            if key in salvaged:
                continue
            value = self._extract_partial_json_value(text, key)
            if value is not None:
                salvaged[key] = value
        useful_keys = {"summary", "half_day_summary", "life_slice", "gm_interpretation", "observed_facts", "child_interpretation"}
        return salvaged if useful_keys.intersection(salvaged) else None

    def _extract_partial_json_value(self, text: str, key: str) -> Any | None:
        marker = f'"{key}"'
        index = text.find(marker)
        if index < 0:
            return None
        colon = text.find(":", index + len(marker))
        if colon < 0:
            return None
        fragment = text[colon + 1 :].lstrip()
        if not fragment:
            return None
        try:
            value, _end = json.JSONDecoder().raw_decode(fragment)
        except json.JSONDecodeError:
            return None
        return value

    def _normalize_outcome(self, data: dict[str, Any], *, raw_outcome: str) -> dict[str, Any]:
        core_keys = ("accepted", "summary", "state_changes", "observations", "memory_writes", "rule_effects", "needs_review", "raw_outcome")
        missing = [key for key in core_keys if key not in data]
        normalized = {
            "accepted": bool(data.get("accepted", True)),
            "summary": str(data.get("summary") or "The action was resolved by the game master."),
            "main_action": str(data.get("main_action") or data.get("summary") or ""),
            "sub_fragments": data.get("sub_fragments") if isinstance(data.get("sub_fragments"), list) else [],
            "observed_facts": data.get("observed_facts") if isinstance(data.get("observed_facts"), list) else [],
            "child_interpretation": str(data.get("child_interpretation") or ""),
            "gm_interpretation": str(data.get("gm_interpretation") or ""),
            "state_update_evidence": data.get("state_update_evidence") if isinstance(data.get("state_update_evidence"), list) else [],
            "half_day_summary": str(data.get("half_day_summary") or data.get("summary") or ""),
            "life_slice": data.get("life_slice") if isinstance(data.get("life_slice"), dict) else {},
            "suggested_updates": data.get("suggested_updates") if isinstance(data.get("suggested_updates"), dict) else {},
            "risk_flags": data.get("risk_flags") if isinstance(data.get("risk_flags"), list) else [],
            "state_changes": data.get("state_changes") if isinstance(data.get("state_changes"), dict) else {},
            "observations": data.get("observations") if isinstance(data.get("observations"), list) else [],
            "memory_writes": data.get("memory_writes") if isinstance(data.get("memory_writes"), list) else [],
            "rule_effects": data.get("rule_effects") if isinstance(data.get("rule_effects"), list) else [],
            "needs_review": bool(data.get("needs_review") or missing),
            "raw_outcome": str(data.get("raw_outcome") or (raw_outcome if missing else "")),
        }
        if missing:
            normalized["schema_missing"] = missing
        return normalized

    def _fallback_outcome(self, *, context: dict[str, Any], action_text: str, reason: str) -> dict[str, Any]:
        agent = context.get("agent") if isinstance(context.get("agent"), dict) else {}
        next_location_id = context.get("suggested_location_id") or agent.get("current_location_id")
        agent_id = agent.get("id")
        return {
            "accepted": True,
            "summary": f"{agent.get('name') or 'The environment'} proceeds deterministically: {action_text}",
            "main_action": action_text,
            "sub_fragments": [],
            "observed_facts": [action_text],
            "child_interpretation": "",
            "gm_interpretation": "Deterministic fallback resolved the action without external GM output.",
            "state_update_evidence": [],
            "half_day_summary": f"{agent.get('name') or 'The environment'} proceeds deterministically.",
            "life_slice": {},
            "suggested_updates": {},
            "risk_flags": [],
            "state_changes": {
                "agent_id": agent_id,
                "current_location_id": next_location_id,
                "current_action": action_text,
            },
            "observations": [{"agent_id": agent_id, "text": action_text}] if agent_id else [],
            "memory_writes": [],
            "rule_effects": [],
            "needs_review": False,
            "raw_outcome": "",
            "fallback_reason": reason,
        }

    def _needs_review_outcome(self, raw: str) -> dict[str, Any]:
        return {
            "accepted": False,
            "summary": "The game master returned an unstructured outcome that needs review.",
            "main_action": "",
            "sub_fragments": [],
            "observed_facts": [],
            "child_interpretation": "",
            "gm_interpretation": "",
            "state_update_evidence": [],
            "half_day_summary": "",
            "life_slice": {},
            "suggested_updates": {},
            "risk_flags": [],
            "state_changes": {},
            "observations": [],
            "memory_writes": [],
            "rule_effects": [],
            "needs_review": True,
            "raw_outcome": raw,
            "gm_source": "unstructured",
        }
