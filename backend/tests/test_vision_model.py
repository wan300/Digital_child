import base64

import httpx
import pytest

from app.core.config import get_settings
from app.models.entities import MediaAsset
from app.services import vision_model
from app.services.vision_model import VisionModelAdapter, VisionModelError, parse_observation_json


def test_vision_adapter_attaches_local_preview_as_image_url(tmp_path) -> None:
    preview_path = tmp_path / "asset-1_thumb.jpg"
    preview_path.write_bytes(b"\xff\xd8\xff\xe0test-jpeg\xff\xd9")
    asset = MediaAsset(
        id="asset-1",
        owner_actor="admin",
        original_filename="play.jpg",
        media_type="image",
        mime_type="image/jpeg",
        sha256="x",
        size_bytes=preview_path.stat().st_size,
        storage_path=str(preview_path),
        preview_refs=[
            {
                "ref": "asset:asset-1#thumb",
                "kind": "thumbnail",
                "path": str(preview_path),
            }
        ],
        metadata_={"width": 1, "height": 1},
    )

    summaries, image_parts = VisionModelAdapter()._asset_payloads([asset])

    assert summaries[0]["visual_input"] == "attached"
    assert summaries[0]["image_inputs"][0]["evidence_ref"] == "asset:asset-1#thumb"
    assert image_parts[0]["type"] == "image_url"
    assert image_parts[0]["image_url"]["url"].startswith("data:image/jpeg;base64,")


def test_vision_adapter_attaches_contact_sheet_as_image_url(tmp_path) -> None:
    sheet_path = tmp_path / "asset-1_sheet-001.jpg"
    sheet_path.write_bytes(b"\xff\xd8\xff\xe0test-jpeg\xff\xd9")
    asset = MediaAsset(
        id="asset-1",
        owner_actor="admin",
        original_filename="clip.mp4",
        media_type="video",
        mime_type="video/mp4",
        sha256="x",
        size_bytes=sheet_path.stat().st_size,
        storage_path=str(tmp_path / "clip.mp4"),
        preview_refs=[
            {
                "ref": "asset:asset-1#sheet-1",
                "kind": "contact_sheet",
                "path": str(sheet_path),
                "frame_count": 8,
            }
        ],
        metadata_={"duration_seconds": 60},
    )

    summaries, image_parts = VisionModelAdapter()._asset_payloads([asset])

    assert summaries[0]["visual_input"] == "attached"
    assert summaries[0]["image_inputs"][0]["kind"] == "contact_sheet"
    assert summaries[0]["image_inputs"][0]["evidence_ref"] == "asset:asset-1#sheet-1"
    assert image_parts[0]["image_url"]["url"].startswith("data:image/jpeg;base64,")


def test_vision_adapter_compresses_oversized_preview_for_inline_payload(tmp_path, monkeypatch) -> None:
    try:
        from PIL import Image
    except Exception:
        pytest.skip("Pillow is required for inline image compression")

    sheet_path = tmp_path / "large-sheet.jpg"
    Image.effect_noise((1600, 1200), 100).convert("RGB").save(sheet_path, "JPEG", quality=95)
    monkeypatch.setattr(vision_model, "MAX_INLINE_IMAGE_BYTES", 100_000)
    assert sheet_path.stat().st_size > vision_model.MAX_INLINE_IMAGE_BYTES
    asset = MediaAsset(
        id="asset-1",
        owner_actor="admin",
        original_filename="clip.mp4",
        media_type="video",
        mime_type="video/mp4",
        sha256="x",
        size_bytes=sheet_path.stat().st_size,
        storage_path=str(tmp_path / "clip.mp4"),
        preview_refs=[
            {
                "ref": "asset:asset-1#sheet-1",
                "kind": "contact_sheet",
                "path": str(sheet_path),
                "frame_count": 8,
            }
        ],
        metadata_={"duration_seconds": 60},
    )

    summaries, image_parts = VisionModelAdapter()._asset_payloads([asset])

    data_url = image_parts[0]["image_url"]["url"]
    payload = base64.b64decode(data_url.split(",", 1)[1])
    assert summaries[0]["visual_input"] == "attached"
    assert data_url.startswith("data:image/jpeg;base64,")
    assert len(payload) <= vision_model.MAX_INLINE_IMAGE_BYTES


@pytest.mark.asyncio
async def test_vision_adapter_prefers_multimodal_config_and_uses_kimi_body(monkeypatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "multimodal_api_key", "vision-key")
    monkeypatch.setattr(settings, "multimodal_base_url", "https://api.moonshot.cn/v1")
    monkeypatch.setattr(settings, "multimodal_model_name", "kimi-k2.6")
    monkeypatch.setattr(settings, "llm_api_key", "general-key")
    monkeypatch.setattr(settings, "llm_base_url", "https://general.example/v1")
    captured: dict[str, object] = {}

    class FakeAsyncClient:
        def __init__(self, *, timeout: float) -> None:
            captured["timeout"] = timeout

        async def __aenter__(self) -> "FakeAsyncClient":
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def post(self, url: str, *, headers: dict[str, str], json: dict[str, object]) -> httpx.Response:
            captured["url"] = url
            captured["headers"] = headers
            captured["body"] = json
            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": '{"observable_summary":"ok"}'}}]},
                request=httpx.Request("POST", url),
            )

    monkeypatch.setattr("app.services.vision_model.httpx.AsyncClient", FakeAsyncClient)

    raw = await VisionModelAdapter()._request_model(
        assets=[],
        structured_setup={},
        target_child_hint=None,
        include_audio=False,
    )

    body = captured["body"]
    assert raw == '{"observable_summary":"ok"}'
    assert captured["url"] == "https://api.moonshot.cn/v1/chat/completions"
    assert captured["headers"] == {"Authorization": "Bearer vision-key", "Content-Type": "application/json"}
    assert body["model"] == "kimi-k2.6"
    assert body["thinking"] == {"type": "disabled"}
    assert "temperature" not in body
    assert "response_format" not in body


@pytest.mark.asyncio
async def test_vision_adapter_falls_back_to_general_llm_config(monkeypatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "multimodal_api_key", "")
    monkeypatch.setattr(settings, "multimodal_base_url", "")
    monkeypatch.setattr(settings, "multimodal_model_name", "")
    monkeypatch.setattr(settings, "llm_api_key", "general-key")
    monkeypatch.setattr(settings, "llm_base_url", "https://general.example/v1")
    monkeypatch.setattr(settings, "chat_model", "general-model")
    captured: dict[str, object] = {}

    class FakeAsyncClient:
        def __init__(self, *, timeout: float) -> None:
            captured["timeout"] = timeout

        async def __aenter__(self) -> "FakeAsyncClient":
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def post(self, url: str, *, headers: dict[str, str], json: dict[str, object]) -> httpx.Response:
            captured["url"] = url
            captured["headers"] = headers
            captured["body"] = json
            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": '{"observable_summary":"ok"}'}}]},
                request=httpx.Request("POST", url),
            )

    monkeypatch.setattr("app.services.vision_model.httpx.AsyncClient", FakeAsyncClient)

    await VisionModelAdapter()._request_model(
        assets=[],
        structured_setup={},
        target_child_hint=None,
        include_audio=False,
    )

    body = captured["body"]
    assert captured["url"] == "https://general.example/v1/chat/completions"
    assert captured["headers"] == {"Authorization": "Bearer general-key", "Content-Type": "application/json"}
    assert body["model"] == "general-model"
    assert body["response_format"] == {"type": "json_object"}
    assert body["temperature"] == 0.2
    assert "thinking" not in body


@pytest.mark.asyncio
async def test_vision_adapter_uses_deterministic_aggregation_by_default(monkeypatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "multimodal_model_aggregation_enabled", False)
    monkeypatch.setattr(settings, "multimodal_api_key", "vision-key")

    async def fail_request(*_args, **_kwargs):
        raise AssertionError("aggregation should not call the model when local aggregation is disabled")

    adapter = VisionModelAdapter()
    monkeypatch.setattr(adapter, "_request_aggregation", fail_request)

    result, raw = await adapter.aggregate(
        batch_results=[
            {
                "observable_summary": "one frame",
                "visible_observations": [{"content": "child is playing", "confidence": 0.7, "evidence_refs": ["asset:a#sheet-1"]}],
                "target_child": {"description": "target child", "confidence": 0.8, "evidence_refs": ["asset:a#sheet-1"]},
            }
        ],
        audio_transcripts=[],
        structured_setup={"child_display_name": "小雨", "age_months": 48},
        target_child_hint=None,
    )

    assert result["visible_observations"][0]["content"] == "child is playing"
    assert '"aggregation": "deterministic"' in raw


def test_parse_observation_json_extracts_wrapped_json() -> None:
    assert parse_observation_json('```json\n{"observable_summary":"ok"}\n```') == {"observable_summary": "ok"}
    assert parse_observation_json('provider text {"observable_summary":"ok"} trailing text') == {
        "observable_summary": "ok"
    }


@pytest.mark.asyncio
async def test_vision_adapter_reports_configured_timeout(monkeypatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "multimodal_api_key", "vision-key")
    monkeypatch.setattr(settings, "multimodal_base_url", "https://api.moonshot.cn/v1")
    monkeypatch.setattr(settings, "multimodal_model_name", "kimi-k2.6")
    monkeypatch.setattr(settings, "multimodal_request_timeout_seconds", 123.0)
    monkeypatch.setattr(settings, "multimodal_rate_limit_retry_delays_seconds", "")

    class FakeAsyncClient:
        def __init__(self, *, timeout: httpx.Timeout) -> None:
            assert timeout.read == 123.0

        async def __aenter__(self) -> "FakeAsyncClient":
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def post(self, url: str, *, headers: dict[str, str], json: dict[str, object]) -> httpx.Response:
            raise httpx.ReadTimeout("slow provider", request=httpx.Request("POST", url))

    monkeypatch.setattr("app.services.vision_model.httpx.AsyncClient", FakeAsyncClient)

    with pytest.raises(VisionModelError) as exc_info:
        await VisionModelAdapter().analyze(
            assets=[],
            structured_setup={},
            target_child_hint=None,
            include_audio=False,
        )

    message = str(exc_info.value)
    assert "vision analysis request timed out after 123s" in message
    assert "model=kimi-k2.6" in message


@pytest.mark.asyncio
async def test_vision_adapter_retries_connect_error_then_succeeds(monkeypatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "multimodal_api_key", "vision-key")
    monkeypatch.setattr(settings, "multimodal_base_url", "https://api.moonshot.cn/v1")
    monkeypatch.setattr(settings, "multimodal_model_name", "kimi-k2.6")
    monkeypatch.setattr(settings, "multimodal_rate_limit_retry_delays_seconds", "0,0")
    calls = 0

    class FakeAsyncClient:
        def __init__(self, *, timeout: httpx.Timeout) -> None:
            pass

        async def __aenter__(self) -> "FakeAsyncClient":
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def post(self, url: str, *, headers: dict[str, str], json: dict[str, object]) -> httpx.Response:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise httpx.ConnectError("temporary network failure", request=httpx.Request("POST", url))
            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": '{"observable_summary":"ok"}'}}]},
                request=httpx.Request("POST", url),
            )

    monkeypatch.setattr("app.services.vision_model.httpx.AsyncClient", FakeAsyncClient)

    result, raw = await VisionModelAdapter().analyze(
        assets=[],
        structured_setup={},
        target_child_hint=None,
        include_audio=False,
    )

    assert calls == 2
    assert raw == '{"observable_summary":"ok"}'
    assert result == {"observable_summary": "ok"}


@pytest.mark.asyncio
async def test_vision_adapter_reports_connect_error_after_retry_budget(monkeypatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "multimodal_api_key", "vision-key")
    monkeypatch.setattr(settings, "multimodal_base_url", "https://api.moonshot.cn/v1")
    monkeypatch.setattr(settings, "multimodal_model_name", "kimi-k2.6")
    monkeypatch.setattr(settings, "multimodal_rate_limit_retry_delays_seconds", "0")
    calls = 0

    class FakeAsyncClient:
        def __init__(self, *, timeout: httpx.Timeout) -> None:
            pass

        async def __aenter__(self) -> "FakeAsyncClient":
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def post(self, url: str, *, headers: dict[str, str], json: dict[str, object]) -> httpx.Response:
            nonlocal calls
            calls += 1
            raise httpx.ConnectError("temporary network failure", request=httpx.Request("POST", url))

    monkeypatch.setattr("app.services.vision_model.httpx.AsyncClient", FakeAsyncClient)

    with pytest.raises(VisionModelError) as exc_info:
        await VisionModelAdapter().analyze(
            assets=[],
            structured_setup={},
            target_child_hint=None,
            include_audio=False,
        )

    message = str(exc_info.value)
    assert calls == 2
    assert "vision analysis request connection failed" in message
    assert "model=kimi-k2.6" in message
    assert "temporary network failure" in message
