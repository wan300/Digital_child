from pathlib import Path

import httpx
import pytest

from app.core.config import get_settings
from app.services.audio_transcription import AudioTranscriptionAdapter


@pytest.mark.asyncio
async def test_audio_transcription_retries_rate_limit_then_succeeds(tmp_path, monkeypatch) -> None:
    settings = get_settings()
    settings.llm_api_key = "test-key"
    settings.multimodal_rate_limit_retry_delays_seconds = "0,0,0"
    audio_path = tmp_path / "audio.mp3"
    audio_path.write_bytes(b"audio")
    adapter = AudioTranscriptionAdapter()
    calls = 0

    async def fake_request(path: Path) -> str:
        nonlocal calls
        calls += 1
        if calls < 3:
            request = httpx.Request("POST", "https://api.example/audio/transcriptions")
            response = httpx.Response(429, request=request)
            raise httpx.HTTPStatusError("rate limited", request=request, response=response)
        return "孩子说想继续搭积木。"

    monkeypatch.setattr(adapter, "_request_transcription", fake_request)
    result = await adapter.transcribe({"ref": "asset:a#audio-1", "path": str(audio_path)})

    assert calls == 3
    assert result["status"] == "completed"
    assert result["text"] == "孩子说想继续搭积木。"
