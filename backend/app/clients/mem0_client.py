from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.clients.vendor_bootstrap import add_vendor_paths
from app.core.config import get_settings


@dataclass
class Mem0SearchResult:
    id: str | None
    content: str
    score: float | None
    metadata: dict[str, Any]


class Mem0Client:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._memory = None
        self._init_attempted = False

    def _config(self) -> dict[str, Any]:
        return {
            "llm": {
                "provider": "openai",
                "config": {
                    "api_key": self.settings.llm_api_key,
                    "model": self.settings.memory_model,
                    "openai_base_url": self.settings.llm_base_url,
                },
            },
            "embedder": {
                "provider": "openai",
                "config": {
                    "api_key": self.settings.llm_api_key,
                    "model": self.settings.embedding_model,
                    "openai_base_url": self.settings.llm_base_url,
                    "embedding_dims": self.settings.embedding_dim,
                },
            },
            "vector_store": {
                "provider": "qdrant",
                "config": {
                    "url": self.settings.qdrant_url,
                    "collection_name": "human_memory_orchestrator",
                    "embedding_model_dims": self.settings.embedding_dim,
                },
            },
        }

    def _get_memory(self):
        if self._init_attempted:
            return self._memory
        self._init_attempted = True
        if not self.settings.llm_api_key or self.settings.llm_api_key == "replace-me":
            return None
        try:
            add_vendor_paths()
            from mem0 import Memory

            self._memory = Memory.from_config(self._config())
        except Exception:
            self._memory = None
        return self._memory

    async def add(self, messages: list[dict[str, str]], *, user_id: str, agent_id: str, run_id: str | None, metadata: dict[str, Any]) -> str | None:
        memory = self._get_memory()
        if memory is None:
            return None
        try:
            result = memory.add(messages, user_id=user_id, agent_id=agent_id, run_id=run_id, metadata=metadata, infer=True)
            items = result.get("results") if isinstance(result, dict) else result
            if isinstance(items, list) and items:
                first = items[0]
                if isinstance(first, dict):
                    return first.get("id")
            return None
        except Exception:
            return None

    async def search(self, query: str, *, user_id: str, agent_id: str, run_id: str | None = None, top_k: int = 8) -> list[Mem0SearchResult]:
        memory = self._get_memory()
        if memory is None:
            return []
        filters: dict[str, Any] = {"user_id": user_id, "agent_id": agent_id}
        if run_id:
            filters["run_id"] = run_id
        try:
            result = memory.search(query=query, filters=filters, top_k=top_k)
            raw_items = result.get("results") if isinstance(result, dict) else result
            items: list[Mem0SearchResult] = []
            for item in raw_items or []:
                if not isinstance(item, dict):
                    continue
                items.append(
                    Mem0SearchResult(
                        id=item.get("id"),
                        content=item.get("memory") or item.get("text") or item.get("content") or "",
                        score=item.get("score"),
                        metadata=item.get("metadata") or {},
                    )
                )
            return [item for item in items if item.content]
        except Exception:
            return []

    async def delete(self, memory_id: str) -> bool:
        memory = self._get_memory()
        if memory is None:
            return False
        try:
            memory.delete(memory_id=memory_id)
            return True
        except Exception:
            return False
