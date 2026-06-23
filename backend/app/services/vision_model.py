from __future__ import annotations

import asyncio
import base64
import json
import mimetypes
import re
from io import BytesIO
from pathlib import Path
from typing import Any

import httpx

from app.core.config import get_settings
from app.models.entities import MediaAsset
from app.simulation.multimodal_prompts import OBSERVATION_JSON_SCHEMA_DESCRIPTION, OBSERVATION_SYSTEM_PROMPT

MAX_INLINE_IMAGE_BYTES = 5 * 1024 * 1024
MAX_INLINE_IMAGE_DIMENSION = 2400
VISUAL_PREVIEW_KINDS = {"thumbnail", "key_frame", "image_reference", "contact_sheet"}


class VisionModelError(RuntimeError):
    pass


class VisionModelAdapter:
    def __init__(self) -> None:
        self.settings = get_settings()

    def _api_key(self) -> str:
        return self.settings.multimodal_api_key or self.settings.llm_api_key

    def _base_url(self) -> str:
        return self.settings.multimodal_base_url or self.settings.llm_base_url

    def _model_name(self) -> str:
        return self.settings.multimodal_model_name or self.settings.chat_model

    def _chat_completions_url(self) -> str:
        return f"{self._base_url().rstrip('/')}/chat/completions"

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._api_key()}", "Content-Type": "application/json"}

    def _uses_kimi_request_shape(self) -> bool:
        model = self._model_name().lower()
        base_url = self._base_url().lower()
        return model == "kimi-k2.6" or ("moonshot" in base_url and model.startswith("kimi-"))

    def _completion_body(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self._model_name(),
            "messages": messages,
            "max_tokens": 4096,
        }
        if self._uses_kimi_request_shape():
            body["thinking"] = {"type": "disabled"}
            return body
        body["response_format"] = {"type": "json_object"}
        body["temperature"] = 0.2
        return body

    async def analyze(
        self,
        *,
        assets: list[MediaAsset],
        structured_setup: dict[str, Any],
        target_child_hint: dict[str, Any] | None = None,
        include_audio: bool = True,
    ) -> tuple[dict[str, Any], str]:
        if self._api_key():
            delays = _retry_delays(self.settings.multimodal_rate_limit_retry_delays_seconds)
            last_error: Exception | None = None
            for attempt, delay in enumerate([0.0, *delays]):
                if delay:
                    await asyncio.sleep(delay)
                try:
                    raw = await asyncio.wait_for(
                        self._request_model(
                            assets=assets,
                            structured_setup=structured_setup,
                            target_child_hint=target_child_hint,
                            include_audio=include_audio,
                        ),
                        timeout=self._overall_timeout(),
                    )
                    return parse_observation_json(raw), raw
                except httpx.HTTPStatusError as exc:
                    last_error = exc
                    if exc.response.status_code == 429 and attempt < len(delays):
                        continue
                    raise VisionModelError(_http_error_message("vision analysis request", exc.response)) from exc
                except httpx.ConnectError as exc:
                    last_error = exc
                    if attempt < len(delays):
                        continue
                    raise VisionModelError(self._connection_error_message("vision analysis request", exc)) from exc
                except (httpx.TimeoutException, TimeoutError) as exc:
                    last_error = exc
                    raise VisionModelError(self._timeout_error_message("vision analysis request")) from exc
                except Exception as exc:
                    last_error = exc
                    raise VisionModelError(f"vision analysis failed: {type(exc).__name__}") from exc
            if last_error is not None:
                raise VisionModelError(f"vision analysis failed: {type(last_error).__name__}") from last_error
        if not self.settings.multimodal_allow_deterministic_fallback:
            raise VisionModelError("vision analysis requires multimodal model API key")
        result = deterministic_observation_result(
            assets=assets,
            structured_setup=structured_setup,
            target_child_hint=target_child_hint,
            include_audio=include_audio,
        )
        return result, json.dumps(result, ensure_ascii=False)

    async def aggregate(
        self,
        *,
        batch_results: list[dict[str, Any]],
        audio_transcripts: list[dict[str, Any]],
        structured_setup: dict[str, Any],
        target_child_hint: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], str]:
        if not self.settings.multimodal_model_aggregation_enabled:
            result = aggregate_deterministic_results(
                batch_results=batch_results,
                audio_transcripts=audio_transcripts,
                structured_setup=structured_setup,
                target_child_hint=target_child_hint,
            )
            return result, json.dumps(
                {"aggregation": "deterministic", "batch_count": len(batch_results), "audio_transcript_count": len(audio_transcripts)},
                ensure_ascii=False,
            )
        if self._api_key() and batch_results:
            delays = _retry_delays(self.settings.multimodal_rate_limit_retry_delays_seconds)
            last_error: Exception | None = None
            for attempt, delay in enumerate([0.0, *delays]):
                if delay:
                    await asyncio.sleep(delay)
                try:
                    raw = await asyncio.wait_for(
                        self._request_aggregation(
                            batch_results=batch_results,
                            audio_transcripts=audio_transcripts,
                            structured_setup=structured_setup,
                            target_child_hint=target_child_hint,
                        ),
                        timeout=self._overall_timeout(),
                    )
                    return parse_observation_json(raw), raw
                except httpx.HTTPStatusError as exc:
                    last_error = exc
                    if exc.response.status_code == 429 and attempt < len(delays):
                        continue
                    raise VisionModelError(_http_error_message("vision aggregation request", exc.response)) from exc
                except httpx.ConnectError as exc:
                    last_error = exc
                    if attempt < len(delays):
                        continue
                    raise VisionModelError(self._connection_error_message("vision aggregation request", exc)) from exc
                except (httpx.TimeoutException, TimeoutError) as exc:
                    last_error = exc
                    raise VisionModelError(self._timeout_error_message("vision aggregation request")) from exc
                except Exception as exc:
                    last_error = exc
                    raise VisionModelError(f"vision aggregation failed: {type(exc).__name__}") from exc
            if last_error is not None:
                raise VisionModelError(f"vision aggregation failed: {type(last_error).__name__}") from last_error
        if not self.settings.multimodal_allow_deterministic_fallback:
            raise VisionModelError("vision aggregation requires successful multimodal model output")
        result = aggregate_deterministic_results(
            batch_results=batch_results,
            audio_transcripts=audio_transcripts,
            structured_setup=structured_setup,
            target_child_hint=target_child_hint,
        )
        return result, json.dumps(result, ensure_ascii=False)

    async def _request_model(
        self,
        *,
        assets: list[MediaAsset],
        structured_setup: dict[str, Any],
        target_child_hint: dict[str, Any] | None,
        include_audio: bool,
    ) -> str:
        asset_summary, image_parts = self._asset_payloads(assets)
        user_text = json.dumps(
            {
                "instruction": (
                    "Analyze only observable visual evidence and return strict JSON. "
                    "For video contact sheets, treat each sheet as sampled frames from one video and cite the sheet evidence_ref. "
                    "Extract concrete scene, gross-motor, fine-motor, emotion, caregiver interaction, social play, environment adaptation, and interest cues. "
                    "This is a batch-level visual pass; keep generated_child_description empty or very brief because final prose is produced in aggregation. "
                    "Do not identify the child, diagnose, infer intelligence, infer family background, or infer stable personality from appearance or voice. "
                    "Return only one JSON object with no Markdown fences or commentary."
                ),
                "schema": OBSERVATION_JSON_SCHEMA_DESCRIPTION,
                "structured_setup": structured_setup,
                "target_child_hint": target_child_hint or {},
                "include_audio": include_audio,
                "assets": asset_summary,
            },
            ensure_ascii=False,
        )
        user_content: str | list[dict[str, Any]]
        user_content = [{"type": "text", "text": user_text}, *image_parts] if image_parts else user_text
        body = self._completion_body(
            [
                {"role": "system", "content": OBSERVATION_SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ]
        )
        async with httpx.AsyncClient(timeout=self._http_timeout()) as client:
            response = await client.post(
                self._chat_completions_url(),
                headers=self._headers(),
                json=body,
            )
            response.raise_for_status()
            data = response.json()
        return data["choices"][0]["message"]["content"]

    async def _request_aggregation(
        self,
        *,
        batch_results: list[dict[str, Any]],
        audio_transcripts: list[dict[str, Any]],
        structured_setup: dict[str, Any],
        target_child_hint: dict[str, Any] | None,
    ) -> str:
        body = self._completion_body(
            [
                {"role": "system", "content": OBSERVATION_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "instruction": (
                                "Merge these visual observations into one conservative child observation draft JSON. "
                                "Use audio transcripts only as weak auxiliary context; do not quote lyrics, transcript text, or speech verbatim in generated_child_description. "
                                "Produce generated_child_description in Simplified Chinese with sections: 当前儿童的主要特征, 简要画像, 观察边界. "
                                "The first section must use numbered points and summarize stable behavior patterns from visual evidence: gross motor, fine motor, emotion, "
                                "caregiver interaction, social play, environment adaptation, and interest preferences. "
                                "Focus on current/overall traits, not a dated growth timeline. Do not include frame ids, evidence refs, audit language, "
                                "identity recognition, diagnosis, intelligence judgment, family-background inference, or appearance/voice-based personality inference. "
                                "Return only one JSON object with no Markdown fences or commentary."
                            ),
                            "schema": OBSERVATION_JSON_SCHEMA_DESCRIPTION,
                            "structured_setup": structured_setup,
                            "target_child_hint": target_child_hint or {},
                            "batch_results": batch_results,
                            "audio_transcripts": audio_transcripts,
                        },
                        ensure_ascii=False,
                    ),
                },
            ]
        )
        async with httpx.AsyncClient(timeout=self._http_timeout()) as client:
            response = await client.post(
                self._chat_completions_url(),
                headers=self._headers(),
                json=body,
            )
            response.raise_for_status()
            data = response.json()
        return data["choices"][0]["message"]["content"]

    def _asset_payloads(self, assets: list[MediaAsset]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        summaries: list[dict[str, Any]] = []
        image_parts: list[dict[str, Any]] = []
        for asset in assets:
            summary: dict[str, Any] = {
                "id": asset.id,
                "media_type": asset.media_type,
                "mime_type": asset.mime_type,
                "preview_refs": asset.preview_refs,
                "metadata": asset.metadata_,
            }
            for image_input in self._image_inputs_for_asset(asset):
                image_parts.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": image_input["data_url"]},
                    }
                )
                summary.setdefault("image_inputs", []).append(
                    {
                        "evidence_ref": image_input["evidence_ref"],
                        "kind": image_input["kind"],
                        "mime_type": image_input["mime_type"],
                    }
                )
            if summary.get("image_inputs"):
                summary["visual_input"] = "attached"
            elif asset.media_type == "video":
                summary["visual_input"] = "metadata_only_no_extracted_frames"
            else:
                summary["visual_input"] = "metadata_only"
            summaries.append(summary)
        return summaries, image_parts

    def _overall_timeout(self) -> float:
        return max(1.0, float(self.settings.multimodal_request_timeout_seconds)) + 5.0

    def _http_timeout(self) -> httpx.Timeout:
        timeout = max(1.0, float(self.settings.multimodal_request_timeout_seconds))
        return httpx.Timeout(timeout=timeout, connect=min(15.0, timeout), read=timeout, write=timeout, pool=15.0)

    def _timeout_error_message(self, action: str) -> str:
        timeout = max(1.0, float(self.settings.multimodal_request_timeout_seconds))
        return (
            f"{action} timed out after {timeout:g}s "
            f"(model={self._model_name()}, base_url={self._base_url()})"
        )

    def _connection_error_message(self, action: str, exc: httpx.ConnectError) -> str:
        detail = str(exc).strip()
        suffix = f": {detail}" if detail else ""
        return f"{action} connection failed (model={self._model_name()}, base_url={self._base_url()}){suffix}"

    def _image_inputs_for_asset(self, asset: MediaAsset) -> list[dict[str, str]]:
        candidates: list[tuple[str, Path, str]] = []
        for ref in asset.preview_refs or []:
            if not isinstance(ref, dict) or not ref.get("path"):
                continue
            kind = str(ref.get("kind") or "preview")
            if kind not in VISUAL_PREVIEW_KINDS:
                continue
            candidates.append((str(ref.get("ref") or f"asset:{asset.id}"), Path(str(ref["path"])), kind))
        if asset.media_type == "image" and asset.storage_path:
            candidates.append((f"asset:{asset.id}#raw-image", Path(asset.storage_path), "raw_image"))

        image_inputs: list[dict[str, str]] = []
        seen_paths: set[str] = set()
        for evidence_ref, path, kind in candidates:
            resolved = str(path)
            if resolved in seen_paths:
                continue
            seen_paths.add(resolved)
            data_url = _file_to_data_url(path)
            if not data_url:
                continue
            image_inputs.append(
                {
                    "evidence_ref": evidence_ref,
                    "kind": kind,
                    "mime_type": data_url.split(";", 1)[0].removeprefix("data:"),
                    "data_url": data_url,
                }
            )
        return image_inputs


def parse_observation_json(raw: str) -> dict[str, Any]:
    text = raw.strip()
    candidates = [text]
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.IGNORECASE | re.DOTALL)
    if fenced:
        candidates.insert(0, fenced.group(1).strip())
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
        raise ValueError("observation model output must be a JSON object")
    extracted = _extract_first_json_object(text)
    if extracted is not None:
        return extracted
    raise ValueError("observation model output must be a JSON object")


def _extract_first_json_object(text: str) -> dict[str, Any] | None:
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", text):
        try:
            parsed, _ = decoder.raw_decode(text[match.start() :])
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _http_error_message(action: str, response: httpx.Response) -> str:
    detail = _response_error_detail(response)
    suffix = f": {detail}" if detail else ""
    return f"{action} failed with HTTP {response.status_code}{suffix}"


def _response_error_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        detail = response.text.strip()
    else:
        detail = json.dumps(payload, ensure_ascii=False)
    return detail[:1000]


def _file_to_data_url(path: Path) -> str | None:
    try:
        if not path.exists() or not path.is_file():
            return None
        mime_type = mimetypes.guess_type(path.name)[0] or "image/jpeg"
        if not mime_type.startswith("image/"):
            return None
        payload = path.read_bytes()
        if len(payload) > MAX_INLINE_IMAGE_BYTES:
            compressed = _compress_image_for_inline(path)
            if compressed is None:
                return None
            mime_type, payload = compressed
        encoded = base64.b64encode(payload).decode("ascii")
    except OSError:
        return None
    return f"data:{mime_type};base64,{encoded}"


def _compress_image_for_inline(path: Path) -> tuple[str, bytes] | None:
    try:
        from PIL import Image, ImageOps

        with Image.open(path) as image:
            image = ImageOps.exif_transpose(image)
            if image.mode not in {"RGB", "L"}:
                image = image.convert("RGB")
            else:
                image = image.copy()
    except Exception:
        return None

    best_payload: bytes | None = None
    max_dimensions = (MAX_INLINE_IMAGE_DIMENSION, 1800, 1400, 1000, 720, 480, 320)
    qualities = (82, 72, 62, 52, 42, 32)
    for max_dimension in max_dimensions:
        candidate = image.copy()
        candidate.thumbnail((max_dimension, max_dimension))
        for quality in qualities:
            buffer = BytesIO()
            candidate.save(buffer, "JPEG", quality=quality, optimize=True)
            payload = buffer.getvalue()
            if best_payload is None or len(payload) < len(best_payload):
                best_payload = payload
            if len(payload) <= MAX_INLINE_IMAGE_BYTES:
                return "image/jpeg", payload
    if best_payload is not None and len(best_payload) <= MAX_INLINE_IMAGE_BYTES:
        return "image/jpeg", best_payload
    return None


def deterministic_observation_result(
    *,
    assets: list[MediaAsset],
    structured_setup: dict[str, Any],
    target_child_hint: dict[str, Any] | None,
    include_audio: bool,
) -> dict[str, Any]:
    child_name = structured_setup.get("child_display_name") or structured_setup.get("child_name") or "孩子"
    age_months = structured_setup.get("age_months") or 48
    evidence_ref = _first_evidence_ref(assets)
    audio_ref = _first_audio_ref(assets)
    has_video = any(asset.media_type == "video" for asset in assets)
    target_confidence = 0.82 if len(assets) <= 1 else 0.62
    if target_child_hint and target_child_hint.get("description"):
        target_confidence = max(target_confidence, 0.8)

    description = (
        "当前儿童的主要特征\n\n"
        f"1. {child_name}是一名约 {age_months} 个月的儿童，上传媒体提供了日常活动、场景和互动的初步可观察线索。\n"
        "2. 目前只看到有限的画面样本，可初步保留为活动参与、动作停留、物件接触和成人陪伴等候选线索。\n"
        "3. 若媒体中存在音频，它只作为成人陪伴、音乐背景或互动语气的弱辅助信息，不直接进入儿童画像正文。\n\n"
        "简要画像\n\n"
        f"{child_name}的当前画像需要基于真实视觉画面继续确认。现阶段只能保守初始化为：可能处在日常活动或互动场景中，"
        "可从动作、兴趣物件、照护者互动和环境适应中提取进一步观察线索。\n\n"
        "观察边界\n\n"
        "仅凭媒体不能可靠判断长期能力、家庭背景、稳定人格、医学或心理诊断，也不能进行身份识别或声纹识别。"
    )

    result: dict[str, Any] = {
        "observable_summary": f"基于上传媒体生成的观察草稿：{child_name}可能处在日常活动或互动场景中，具体结论需要人工审核。",
        "generated_child_description": description,
        "target_child": {
            "description": target_child_hint.get("description") if target_child_hint else "媒体中的主要儿童",
            "confidence": target_confidence,
            "evidence_refs": [evidence_ref],
            "operator_confirmed": False,
        },
        "visible_observations": [
            {
                "content": "媒体提供了可观察的场景、活动或互动线索，可作为后续人工审核的视觉证据。",
                "confidence": 0.7,
                "evidence_refs": [evidence_ref],
                "scope": "reviewable_observation",
            }
        ],
        "audio_observations": [],
        "non_identifying_appearance": [
            {
                "content": "外观线索仅可保留非识别性的场景化描述，不用于身份识别。",
                "confidence": 0.55,
                "evidence_refs": [evidence_ref],
            }
        ],
        "behavior_signals": [
            {
                "content": "可将媒体中的动作、停留、互动方向和物件操作作为行为信号候选。",
                "confidence": 0.66,
                "evidence_refs": [evidence_ref],
            }
        ],
        "temperament_hypotheses": [
            {
                "content": "可能在熟悉场景中更愿意参与互动；该项仅是气质线索候选。",
                "confidence": 0.52,
                "evidence_refs": [evidence_ref],
            }
        ],
        "interests": [
            {
                "content": "对媒体中的活动或物件可能表现出兴趣，需要结合多段画面确认。",
                "confidence": 0.58,
                "evidence_refs": [evidence_ref],
            }
        ],
        "development_hints": {
            "social_cooperation": [
                {
                    "content": "互动片段可作为社会合作观察线索，但不构成发展结论。",
                    "confidence": 0.5,
                    "evidence_refs": [evidence_ref],
                }
            ]
        },
        "avatar_brief": {
            "style": "非识别性、卡通化、避免真实儿童复制",
            "evidence_refs": [evidence_ref],
        },
        "initial_memory_candidates": [
            {
                "content": f"{child_name}有一次被观察到参与日常互动的经历，细节需要人工确认。",
                "confidence": 0.5,
                "evidence_refs": [evidence_ref],
            }
        ],
        "risk_flags": [],
        "unknowns": ["无法从媒体可靠判断长期能力、家庭背景或稳定人格。"],
    }
    if include_audio and has_video and audio_ref:
        result["audio_observations"].append(
            {
                "content": "音频仅提示可能存在成人陪伴、音乐背景或互动语气，不能替代视觉观察。",
                "confidence": 0.45,
                "evidence_refs": [audio_ref],
                "scope": "reviewable_audio_summary",
            }
        )
    return result


def aggregate_deterministic_results(
    *,
    batch_results: list[dict[str, Any]],
    audio_transcripts: list[dict[str, Any]],
    structured_setup: dict[str, Any],
    target_child_hint: dict[str, Any] | None,
) -> dict[str, Any]:
    fallback = deterministic_observation_result(
        assets=[],
        structured_setup=structured_setup,
        target_child_hint=target_child_hint,
        include_audio=True,
    )
    result = batch_results[0] if batch_results else fallback
    merged = dict(result)
    merged["visible_observations"] = _merge_rows(batch_results, "visible_observations")
    merged["behavior_signals"] = _merge_rows(batch_results, "behavior_signals")
    merged["temperament_hypotheses"] = _merge_rows(batch_results, "temperament_hypotheses")
    merged["interests"] = _merge_rows(batch_results, "interests")
    merged["initial_memory_candidates"] = _merge_rows(batch_results, "initial_memory_candidates")
    merged["unknowns"] = [item for row in batch_results for item in (row.get("unknowns") or [])] or list(fallback["unknowns"])
    audio_rows = []
    for transcript in audio_transcripts:
        ref = str(transcript.get("ref") or "asset:unknown#audio")
        if transcript.get("text"):
            audio_rows.append(
                {
                    "content": "音频片段包含可听到的人声、音乐或互动背景，已仅作为弱辅助线索保留；最终描述不直接引用转写原文。",
                    "confidence": 0.45,
                    "evidence_refs": [ref],
                    "scope": "reviewable_audio_summary",
                    "transcript_available": True,
                }
            )
    merged["audio_observations"] = audio_rows or _merge_rows(batch_results, "audio_observations")
    merged["observable_summary"] = str(merged.get("observable_summary") or fallback["observable_summary"])
    merged["generated_child_description"] = str(merged.get("generated_child_description") or fallback["generated_child_description"])
    return merged


def _merge_rows(batch_results: list[dict[str, Any]], key: str) -> list[Any]:
    rows: list[Any] = []
    for result in batch_results:
        value = result.get(key)
        if isinstance(value, list):
            rows.extend(value)
    return rows


def _first_evidence_ref(assets: list[MediaAsset]) -> str:
    for asset in assets:
        for ref in asset.preview_refs or []:
            if isinstance(ref, dict) and ref.get("ref"):
                return str(ref["ref"])
    return f"asset:{assets[0].id}" if assets else "text:setup"


def _first_audio_ref(assets: list[MediaAsset]) -> str | None:
    for asset in assets:
        metadata = asset.metadata_ or {}
        audio_refs = metadata.get("audio_refs") if isinstance(metadata, dict) else None
        if isinstance(audio_refs, list) and audio_refs:
            ref = audio_refs[0]
            if isinstance(ref, dict) and ref.get("ref"):
                return str(ref["ref"])
    return None


def _retry_delays(value: str) -> list[float]:
    delays: list[float] = []
    for part in value.split(","):
        try:
            delays.append(max(0.0, float(part.strip())))
        except ValueError:
            continue
    return delays
