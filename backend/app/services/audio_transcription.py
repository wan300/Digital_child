from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import httpx

from app.core.config import get_settings


class AudioTranscriptionAdapter:
    def __init__(self) -> None:
        self.settings = get_settings()

    async def transcribe(self, audio_ref: dict[str, Any]) -> dict[str, Any]:
        path = Path(str(audio_ref.get("path") or ""))
        ref = str(audio_ref.get("ref") or "asset:unknown#audio")
        if not path.exists() or not path.is_file():
            return {"ref": ref, "status": "unavailable", "text": "", "error": "audio segment file is unavailable"}
        if not self.settings.llm_api_key:
            return {"ref": ref, "status": "skipped_no_api_key", "text": "", "error": ""}
        delays = _retry_delays(self.settings.multimodal_rate_limit_retry_delays_seconds)
        for attempt in range(len(delays) + 1):
            try:
                text = await self._request_transcription(path)
                return {"ref": ref, "status": "completed", "text": text, "error": ""}
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 429 and attempt < len(delays):
                    await asyncio.sleep(delays[attempt])
                    continue
                return {
                    "ref": ref,
                    "status": "rate_limited_failed" if exc.response.status_code == 429 else "failed",
                    "text": "",
                    "error": f"ASR request failed with HTTP {exc.response.status_code}",
                }
            except Exception as exc:
                return {"ref": ref, "status": "failed", "text": "", "error": f"ASR request failed: {type(exc).__name__}"}
        return {"ref": ref, "status": "failed", "text": "", "error": "ASR retry budget exhausted"}

    async def _request_transcription(self, path: Path) -> str:
        async with httpx.AsyncClient(timeout=self.settings.multimodal_request_timeout_seconds) as client:
            with path.open("rb") as handle:
                response = await client.post(
                    f"{self.settings.llm_base_url.rstrip('/')}/audio/transcriptions",
                    headers={"Authorization": f"Bearer {self.settings.llm_api_key}"},
                    data={"model": self.settings.multimodal_asr_model_name},
                    files={"file": (path.name, handle, "audio/mpeg")},
                )
            response.raise_for_status()
            data = response.json()
        if isinstance(data, dict):
            return str(data.get("text") or data.get("transcription") or "")
        return str(data)


def _retry_delays(value: str) -> list[float]:
    delays: list[float] = []
    for part in value.split(","):
        try:
            delays.append(max(0.0, float(part.strip())))
        except ValueError:
            continue
    return delays
