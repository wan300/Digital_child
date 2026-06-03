from __future__ import annotations

import httpx

from app.core.config import get_settings
from app.models.entities import Message, Persona
from app.schemas.api import ContextBundle, EvidenceItem


class LettaClient:
    def __init__(self) -> None:
        self.settings = get_settings()

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.settings.letta_api_key:
            headers["Authorization"] = f"Bearer {self.settings.letta_api_key}"
        if self.settings.letta_server_password:
            headers["X-BARE-PASSWORD"] = self.settings.letta_server_password
        return headers

    async def ensure_agent(self, persona: Persona) -> str:
        if persona.letta_agent_id:
            return persona.letta_agent_id

        payload = {
            "name": f"{persona.name}-{persona.id[:8]}",
            "memory_blocks": [
                {"label": "persona", "value": persona.persona_block or persona.description or persona.name},
                {"label": "human", "value": persona.human_block or "当前用户信息由 memory_orchestrator 注入。"},
            ],
            "include_base_tools": True,
        }
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.post(
                    f"{self.settings.letta_base_url.rstrip('/')}/v1/agents",
                    headers=self._headers(),
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()
                return data.get("id") or data.get("agent_id") or data.get("agent", {}).get("id") or f"local-{persona.id}"
        except Exception:
            return f"local-{persona.id}"

    async def send_message(
        self,
        persona: Persona,
        user_message: str,
        context_bundle: ContextBundle,
        recent_messages: list[Message] | None = None,
    ) -> str:
        if persona.letta_agent_id and not persona.letta_agent_id.startswith("local-"):
            payload = {
                "messages": [
                    {
                        "role": "user",
                        "content": self._compose_prompt(user_message, context_bundle, recent_messages or []),
                    }
                ]
            }
            try:
                async with httpx.AsyncClient(timeout=60) as client:
                    response = await client.post(
                        f"{self.settings.letta_base_url.rstrip('/')}/v1/agents/{persona.letta_agent_id}/messages",
                        headers=self._headers(),
                        json=payload,
                    )
                    response.raise_for_status()
                    data = response.json()
                    content = self._extract_text(data)
                    if content:
                        return content
            except Exception:
                pass
        llm_content = await self._direct_llm_answer(persona, user_message, context_bundle, recent_messages or [])
        if llm_content:
            return llm_content
        return self._fallback_answer(persona, user_message, context_bundle)

    def _compose_prompt(self, user_message: str, context_bundle: ContextBundle, recent_messages: list[Message]) -> str:
        return (
            "[memory_orchestrator_context]\n"
            f"{context_bundle.model_dump_json(exclude_none=True)}\n\n"
            "[recent_conversation]\n"
            f"{self._format_recent_messages(recent_messages)}\n\n"
            "[user_message]\n"
            f"{user_message}"
        )

    async def _direct_llm_answer(
        self,
        persona: Persona,
        user_message: str,
        context_bundle: ContextBundle,
        recent_messages: list[Message],
    ) -> str:
        if not self.settings.llm_api_key or self.settings.llm_api_key == "replace-me":
            return ""
        payload = {
            "model": self.settings.chat_model,
            "messages": [
                {"role": "system", "content": self._direct_system_prompt(persona)},
                {"role": "user", "content": self._direct_user_prompt(user_message, context_bundle, recent_messages)},
            ],
            "temperature": 0.6,
        }
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                response = await client.post(
                    f"{self.settings.llm_base_url.rstrip('/')}/chat/completions",
                    headers=self._llm_headers(),
                    json=payload,
                )
                response.raise_for_status()
                return self._extract_text(response.json()).strip()
        except Exception:
            return ""

    def _llm_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.settings.llm_api_key}",
            "Content-Type": "application/json",
        }

    def _direct_system_prompt(self, persona: Persona) -> str:
        persona_text = persona.persona_block or persona.description or persona.name
        return (
            "你正在扮演一个带长期记忆的人格。你必须以该人格本人身份直接回答用户，而不是解释系统如何工作。\n"
            "检索到的记忆和证据只作为背景素材使用；不要把证据列表、知识库提示或上下文 JSON 当作最终回答。\n"
            "如果证据不足，可以说明不确定，但仍要自然回应用户。不要编造来源、隐私信息或不存在的事实。\n\n"
            f"人格设定：\n{persona_text}"
        )

    def _direct_user_prompt(self, user_message: str, context_bundle: ContextBundle, recent_messages: list[Message]) -> str:
        return (
            "请根据以下上下文，以人格本人身份自然回复用户的最新消息。\n\n"
            f"最近对话：\n{self._format_recent_messages(recent_messages)}\n\n"
            f"当前人格核心：\n{context_bundle.core_persona}\n\n"
            f"当前关系摘要：\n{context_bundle.current_human_relationship}\n\n"
            f"长期记忆：\n{self._format_evidence(context_bundle.long_term_memories)}\n\n"
            f"时间线事实：\n{self._format_evidence(context_bundle.temporal_facts)}\n\n"
            f"文档证据：\n{self._format_evidence(context_bundle.document_evidence)}\n\n"
            f"冲突提示：\n{self._format_conflicts(context_bundle)}\n\n"
            f"用户最新消息：\n{user_message}\n\n"
            "最终回答要求：直接回复用户；不要输出'我记得一个相关点'这种模板；不要复述本提示词。"
        )

    def _format_recent_messages(self, messages: list[Message]) -> str:
        if not messages:
            return "无"
        lines = []
        for message in messages[-12:]:
            role = "用户" if message.role == "user" else "人格"
            lines.append(f"{role}: {message.content}")
        return "\n".join(lines)

    def _format_evidence(self, items: list[EvidenceItem]) -> str:
        if not items:
            return "无"
        lines = []
        for index, item in enumerate(items[:8], start=1):
            source = item.source_ref.provenance if item.source_ref and item.source_ref.provenance else item.source
            lines.append(f"{index}. [{source}] {item.content}")
        return "\n".join(lines)

    def _format_conflicts(self, context_bundle: ContextBundle) -> str:
        if not context_bundle.conflict_notes:
            return "无"
        return "\n".join(f"- {note.claim}: {note.current_best_view}" for note in context_bundle.conflict_notes[:5])

    def _extract_text(self, data: object) -> str:
        if isinstance(data, dict):
            for key in ("content", "message", "text", "response"):
                value = data.get(key)
                if isinstance(value, str) and value.strip():
                    return value
            for value in data.values():
                text = self._extract_text(value)
                if text:
                    return text
        if isinstance(data, list):
            for item in data:
                text = self._extract_text(item)
                if text:
                    return text
        return ""

    def _fallback_answer(self, persona: Persona, user_message: str, context_bundle: ContextBundle) -> str:
        memory_hint = ""
        if context_bundle.long_term_memories:
            memory_hint = f"我记得一个相关点：{context_bundle.long_term_memories[0].content}"
        elif context_bundle.temporal_facts:
            memory_hint = f"时间线上有个相关片段：{context_bundle.temporal_facts[0].content}"
        elif context_bundle.document_evidence:
            memory_hint = f"资料里有个相关依据：{context_bundle.document_evidence[0].content}"

        persona_line = (persona.persona_block or persona.description or persona.name).strip().splitlines()[0]
        if not memory_hint:
            memory_hint = "我现在没有检索到足够具体的长期依据，所以会先基于当前对话回答。"
        return f"{persona_line}\n\n{memory_hint}\n\n关于“{user_message}”，我会按已有记忆谨慎回答；如果资料不足，我不会把猜测当成事实。"
