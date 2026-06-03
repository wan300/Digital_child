from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import get_settings


@dataclass
class LightRAGResult:
    content: str
    source_id: str | None
    score: float | None
    metadata: dict[str, Any]


class LightRAGClient:
    def __init__(self) -> None:
        self.settings = get_settings()

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.settings.lightrag_api_key:
            headers["X-API-Key"] = self.settings.lightrag_api_key
            headers["Authorization"] = f"Bearer {self.settings.lightrag_api_key}"
        return headers

    async def insert_text(self, *, text: str, filename: str, workspace: str) -> str | None:
        payload = {"text": text, "description": filename, "workspace": workspace}
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(
                    f"{self.settings.lightrag_base_url.rstrip('/')}/documents/text",
                    headers=self._headers(),
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()
                return data.get("track_id") or data.get("id") or data.get("document_id")
        except Exception:
            return None

    async def query(self, *, query: str, mode: str = "hybrid", top_k: int = 5) -> list[LightRAGResult]:
        payload = {
            "query": query,
            "mode": mode,
            "top_k": top_k,
            "include_references": True,
            "include_chunk_content": True,
        }
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                response = await client.post(
                    f"{self.settings.lightrag_base_url.rstrip('/')}/query",
                    headers=self._headers(),
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()
        except Exception:
            return []

        results: list[LightRAGResult] = []
        for ref in data.get("references") or []:
            content = ref.get("content")
            text = "\n\n".join(str(part) for part in content) if isinstance(content, list) else str(content or "")
            if text.strip():
                results.append(
                    LightRAGResult(
                        content=text,
                        source_id=ref.get("reference_id") or ref.get("file_path"),
                        score=ref.get("score"),
                        metadata=ref,
                    )
                )
        if not results and isinstance(data.get("response"), str):
            results.append(LightRAGResult(content=data["response"], source_id=None, score=None, metadata=data))
        return results[:top_k]

    async def health(self) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                response = await client.get(f"{self.settings.lightrag_base_url.rstrip('/')}/health", headers=self._headers())
                return {"ok": response.status_code < 500, "status_code": response.status_code}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
