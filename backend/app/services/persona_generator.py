from __future__ import annotations

import json
import re
from typing import Any

import httpx
from pydantic import ValidationError

from app.core.config import get_settings
from app.schemas.api import GeneratedMemoryDraft, PersonaGenerateRequest, PersonaGenerateResponse


class PersonaGenerationError(ValueError):
    pass


class PersonaGenerationConfigError(PersonaGenerationError):
    pass


class PersonaGenerator:
    def __init__(self) -> None:
        self.settings = get_settings()

    async def generate(self, payload: PersonaGenerateRequest) -> PersonaGenerateResponse:
        if not self.settings.llm_api_key or self.settings.llm_api_key == "replace-me":
            raise PersonaGenerationConfigError("LLM_API_KEY is not configured")
        required_terms = self._required_terms(payload.description)
        content = await self._request_completion(payload.description, payload.memory_count, required_terms)
        draft = self._parse_response(content, payload.memory_count)
        self._validate_alignment(draft, required_terms)
        return draft

    async def _request_completion(self, description: str, memory_count: int, required_terms: list[str]) -> str:
        required_terms_text = "、".join(required_terms) if required_terms else "the user's described role and setting"
        request_body = {
            "model": self.settings.chat_model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You generate fictional AI personas for a memory orchestration system. "
                        "Return only valid JSON. All generated values must be written in Simplified Chinese. "
                        "Do not generate real-person claims, private credentials, phone numbers, addresses, "
                        "identity document numbers, or other sensitive personal data."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        "Create one fictional persona from this description.\n\n"
                        f"Description:\n{description}\n\n"
                        f"Memory count: {memory_count}\n\n"
                        "The persona must match the description exactly in occupation, setting, abilities, "
                        "tone, and constraints. Do not replace the described role with an unrelated role. "
                        "Invent only details that are consistent with the description.\n\n"
                        "The generated description, persona_block, or memories must include these exact required terms: "
                        f"{required_terms_text}.\n\n"
                        "Return this JSON object shape exactly:\n"
                        "{\n"
                        '  "name": "short persona name",\n'
                        '  "description": "one concise paragraph",\n'
                        '  "persona_block": "stable role, style, boundaries, values, and voice",\n'
                        '  "human_block": "neutral note for unknown current user relationship",\n'
                        '  "memories": [\n'
                        '    {"content": "persona background memory", "memory_type": "fact", "confidence": 0.8}\n'
                        "  ]\n"
                        "}\n\n"
                        "Memory types should be one of: identity, fact, event, preference, habit, goal. "
                        "Memories are the persona's own background and history, not shared history with the current user."
                    ),
                },
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.35,
        }
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                response = await client.post(
                    f"{self.settings.llm_base_url.rstrip('/')}/chat/completions",
                    headers=self._headers(),
                    json=request_body,
                )
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPError as exc:
            raise PersonaGenerationError(f"LLM request failed: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise PersonaGenerationError("LLM response was not JSON") from exc
        return self._extract_message_text(data)

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.settings.llm_api_key}",
            "Content-Type": "application/json",
        }

    def _extract_message_text(self, data: dict[str, Any]) -> str:
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            raise PersonaGenerationError("LLM response did not include choices")
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if isinstance(content, list):
            content = "".join(str(part.get("text") or part.get("content") or "") for part in content if isinstance(part, dict))
        if not isinstance(content, str) or not content.strip():
            raise PersonaGenerationError("LLM response did not include message content")
        return content

    def _parse_response(self, content: str, memory_count: int) -> PersonaGenerateResponse:
        raw = self._strip_json_fence(content)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise PersonaGenerationError("LLM returned invalid JSON") from exc
        if not isinstance(data, dict):
            raise PersonaGenerationError("LLM returned a non-object JSON value")
        try:
            draft = PersonaGenerateResponse.model_validate(data)
        except ValidationError as exc:
            raise PersonaGenerationError(f"LLM response is missing required fields: {exc}") from exc
        memories = [memory for memory in draft.memories if memory.content.strip()]
        if not memories:
            raise PersonaGenerationError("LLM response did not include any memories")
        return draft.model_copy(update={"memories": memories[:memory_count]})

    def _strip_json_fence(self, content: str) -> str:
        stripped = content.strip()
        match = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", stripped, flags=re.DOTALL | re.IGNORECASE)
        return match.group(1).strip() if match else stripped

    def _required_terms(self, description: str) -> list[str]:
        terms: list[str] = []
        for part in re.split(r"[，。；、,.?？！!;\s]+", description):
            term = part.strip()
            term = re.sub(r"^(?:(?:一个|一位|虚构的|虚构|擅长|并用|用|在))+", "", term)
            term = re.sub(r"(的)$", "", term)
            if 2 <= len(term) <= 24 and term not in terms:
                terms.append(term)
        return terms[:4]

    def _validate_alignment(self, draft: PersonaGenerateResponse, required_terms: list[str]) -> None:
        if not required_terms:
            return
        combined = " ".join(
            [
                draft.name,
                draft.description,
                draft.persona_block,
                draft.human_block,
                " ".join(memory.content for memory in draft.memories),
            ]
        )
        matched = [term for term in required_terms if term in combined]
        minimum_matches = min(2, len(required_terms))
        missing = [term for term in required_terms if term not in combined]
        if required_terms[0] not in matched or len(matched) < minimum_matches:
            raise PersonaGenerationError(f"LLM response did not match description; missing required terms: {', '.join(missing)}")


def normalize_generated_memory(memory: GeneratedMemoryDraft) -> GeneratedMemoryDraft:
    allowed_types = {"identity", "fact", "event", "preference", "habit", "goal"}
    memory_type = memory.memory_type if memory.memory_type in allowed_types else "fact"
    return memory.model_copy(update={"content": memory.content.strip(), "memory_type": memory_type})
