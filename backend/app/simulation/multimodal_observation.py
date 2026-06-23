from __future__ import annotations

import asyncio
import json
import re
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.entities import (
    AuditLog,
    ChildMultimodalObservationDraft,
    ChildWorldDraft,
    MediaAnalysisJob,
    MediaAsset,
    ObservationReviewDecision,
    new_id,
)
from app.schemas.api import (
    AssetStates,
    AuthorizationConfirmation,
    ChildObservationAnalysisJobCreate,
    ChildObservationStructuredSetup,
    ChildWorldDraftRequest,
    ObservationDescriptionAcceptRequest,
    ObservationReviewItem,
    ObservationReviewRequest,
)
from app.services.audio_transcription import AudioTranscriptionAdapter
from app.services.media_preprocessor import MediaPreprocessor
from app.services.media_storage import MediaStorage, media_type_from_content, sanitize_filename
from app.services.vision_model import VisionModelAdapter
from app.simulation.child_growth import ChildWorldDraftService
from app.simulation.multimodal_prompts import OBSERVATION_PROMPT_VERSION

PROHIBITED_PATTERNS = (
    ("face_recognition", r"人脸识别|身份识别|识别身份|识别真实身份|identity matching|face recognition|match.*identity"),
    ("voiceprint", r"声纹|voiceprint|voice biometric|biometric voice"),
    ("diagnosis", r"诊断|自闭症|adhd|抑郁症|medical diagnosis|psychological diagnosis"),
    ("intelligence", r"智力|智商|iq\b|intelligence"),
    ("appearance_personality", r"根据.*长相.*性格|长相.*人格|appearance.*personality|looks.*personality"),
)

HIGH_RISK_PATTERNS = (
    ("real_identifier", r"\b\d{15,18}\b|身份证|护照|真实姓名"),
    ("school_or_address", r"真实学校|家庭住址|详细地址"),
    ("medical_record", r"病历|诊断证明|病例|处方"),
    ("severe_harm", r"虐待|自伤|自杀|严重创伤|暴力伤害|违法伤害"),
)

REVIEW_LIST_FIELDS = {
    "visible_observations",
    "audio_observations",
    "non_identifying_appearance",
    "behavior_signals",
    "temperament_hypotheses",
    "interests",
    "initial_memory_candidates",
    "unknowns",
}

VISUAL_PREVIEW_KINDS = {"thumbnail", "key_frame", "contact_sheet"}


class ChildMultimodalObservationService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.storage = MediaStorage()
        self.preprocessor = MediaPreprocessor()
        self.vision = VisionModelAdapter()
        self.asr = AudioTranscriptionAdapter()

    async def create_media_asset(
        self,
        session: AsyncSession,
        *,
        filename: str,
        content_type: str,
        data: bytes,
        actor: str,
    ) -> MediaAsset:
        safe_name = sanitize_filename(filename)
        media_type = media_type_from_content(content_type, safe_name)
        if media_type is None:
            raise ValueError("unsupported media type")
        asset = MediaAsset(
            id=new_id(),
            owner_actor=actor,
            original_filename=safe_name,
            media_type=media_type,
            mime_type=content_type or "application/octet-stream",
            status="uploaded",
        )
        storage_path, sha256, size_bytes = await self.storage.save_bytes(
            asset_id=asset.id,
            filename=safe_name,
            data=data,
            max_bytes=self.settings.multimodal_max_upload_bytes,
        )
        asset.storage_path = str(storage_path)
        asset.sha256 = sha256
        asset.size_bytes = size_bytes
        asset.preview_refs = []
        asset.status = "uploaded"
        asset.metadata_ = {"mime_type": asset.mime_type}
        session.add(asset)
        self._audit(session, actor=actor, action="child_observation.media.upload", target_type="media_asset", target_id=asset.id, payload={"media_type": media_type})
        await session.flush()
        return asset

    async def create_media_asset_from_upload(
        self,
        session: AsyncSession,
        *,
        filename: str,
        content_type: str,
        upload: object,
        actor: str,
    ) -> MediaAsset:
        safe_name = sanitize_filename(filename)
        media_type = media_type_from_content(content_type, safe_name)
        if media_type is None:
            raise ValueError("unsupported media type")
        asset = MediaAsset(
            id=new_id(),
            owner_actor=actor,
            original_filename=safe_name,
            media_type=media_type,
            mime_type=content_type or "application/octet-stream",
            status="uploaded",
        )
        storage_path, sha256, size_bytes = await self.storage.save_upload_stream(
            asset_id=asset.id,
            filename=safe_name,
            upload=upload,
            max_bytes=self.settings.multimodal_max_upload_bytes,
        )
        asset.storage_path = str(storage_path)
        asset.sha256 = sha256
        asset.size_bytes = size_bytes
        asset.preview_refs = []
        asset.metadata_ = {"mime_type": asset.mime_type}
        session.add(asset)
        self._audit(session, actor=actor, action="child_observation.media.upload", target_type="media_asset", target_id=asset.id, payload={"media_type": media_type})
        await session.flush()
        return asset

    async def create_analysis_job(
        self,
        session: AsyncSession,
        *,
        payload: ChildObservationAnalysisJobCreate,
        actor: str,
    ) -> tuple[MediaAnalysisJob, ChildMultimodalObservationDraft | None]:
        assets = await self._load_assets(session, payload.asset_ids)
        if not assets:
            raise ValueError("analysis requires at least one media asset")
        job = MediaAnalysisJob(
            status="queued",
            asset_ids=[asset.id for asset in assets],
            analyzed_asset_ids=[],
            pending_asset_ids=[asset.id for asset in assets],
            skipped_asset_ids=[],
            excluded_asset_ids=[],
            model_provider=(
                "openai-compatible"
                if self.settings.multimodal_api_key or self.settings.llm_api_key
                else ("deterministic-fallback" if self.settings.multimodal_allow_deterministic_fallback else "unconfigured")
            ),
            model_name=self.settings.multimodal_model_name or self.settings.chat_model,
            prompt_version=OBSERVATION_PROMPT_VERSION,
            attempt_count=0,
            normalized_result={
                "phase": "queued",
                "request": payload.model_dump(mode="json"),
                "asset_progress": _initial_asset_progress(assets),
                "frame_progress": {"total": 0, "analyzed": 0, "failed": 0, "pending": 0},
            },
        )
        session.add(job)
        await session.flush()
        self._audit(
            session,
            actor=actor,
            action="child_observation.analysis.queued",
            target_type="media_analysis_job",
            target_id=job.id,
            payload={"asset_count": len(assets)},
        )
        return job, None

    async def process_analysis_job(self, session: AsyncSession, *, job_id: str, actor: str) -> ChildMultimodalObservationDraft | None:
        job = await session.get(MediaAnalysisJob, job_id)
        if job is None:
            return None
        if job.status in {"completed", "partial", "failed", "cancelled"}:
            return await self._draft_for_job(session, job.id)
        request = _as_dict((job.normalized_result or {}).get("request"))
        payload = ChildObservationAnalysisJobCreate.model_validate(request)
        assets = await self._load_assets(session, payload.asset_ids)
        job.status = "running"
        job.error_message = ""
        job.started_at = job.started_at or datetime.now(UTC)
        job.attempt_count += 1
        progress = _job_progress(job)
        try:
            await self._persist_job_phase(session, job, "extracting_frames", progress=progress)
            await self._preprocess_assets(session, job=job, assets=assets, progress=progress)
            frames = _frame_refs_from_assets(assets)
            already_analyzed = sum(int(_as_dict(row).get("frame_analyzed") or 0) for row in _as_dict(progress.get("asset_progress")).values())
            already_analyzed = min(already_analyzed, len(frames))
            progress["frame_progress"] = {
                "total": len(frames),
                "analyzed": already_analyzed,
                "failed": int(_as_dict(progress.get("frame_progress")).get("failed") or 0),
                "pending": max(0, len(frames) - already_analyzed),
            }
            await self._persist_job_phase(session, job, "transcribing_audio", progress=progress)
            audio_transcripts = await self._transcribe_assets(session, job=job, assets=assets, progress=progress, include_audio=payload.include_audio)
            await self._persist_job_phase(session, job, "analyzing_frames", progress=progress)
            batch_results, raw_batches = await self._analyze_frame_batches(
                session=session,
                job=job,
                assets=assets,
                frames=frames,
                setup=payload.structured_setup.model_dump(),
                target_child_hint=payload.target_child_hint,
                progress=progress,
            )
            await self._persist_job_phase(session, job, "aggregating", progress=progress)
            normalized, raw_response = await self.vision.aggregate(
                batch_results=batch_results,
                audio_transcripts=audio_transcripts,
                structured_setup=payload.structured_setup.model_dump(),
                target_child_hint=payload.target_child_hint,
            )
            normalized["audio_observations"] = list(normalized.get("audio_observations") or []) + _audio_summaries_from_transcripts(audio_transcripts)
            normalized = self._normalize_observation_result(
                normalized,
                setup=payload.structured_setup,
                assets=assets,
                include_audio=payload.include_audio,
            )
            job.normalized_result = {**normalized, **progress, "phase": "completed"}
            job.raw_response = json.dumps(
                {
                    "visual_inputs": frames,
                    "batch_results": batch_results,
                    "batches": raw_batches,
                    "aggregate": raw_response,
                    "audio_transcript_count": len(audio_transcripts),
                },
                ensure_ascii=False,
            )
            job.target_child = normalized.get("target_child") or {}
            failed_assets = [asset_id for asset_id, row in _as_dict(progress.get("asset_progress")).items() if _as_dict(row).get("status") == "failed"]
            job.status = "partial" if failed_assets else "completed"
            job.error_message = ""
            job.analyzed_asset_ids = [asset.id for asset in assets if asset.id not in failed_assets]
            job.pending_asset_ids = []
            job.skipped_asset_ids = failed_assets
            job.completed_at = datetime.now(UTC)
            draft = self._draft_from_result(job=job, setup=payload.structured_setup, result=normalized)
            session.add(draft)
            self._audit(
                session,
                actor=actor,
                action="child_observation.analysis.complete",
                target_type="media_analysis_job",
                target_id=job.id,
                payload={"draft_id": draft.id, "status": job.status},
            )
            await session.flush()
            await session.commit()
            return draft
        except Exception as exc:
            await self._record_analysis_failure(session, job_id=job_id, actor=actor, error=exc)
            return None

    async def _preprocess_assets(
        self,
        session: AsyncSession,
        *,
        job: MediaAnalysisJob,
        assets: list[MediaAsset],
        progress: dict[str, Any],
    ) -> None:
        for asset in assets:
            asset_progress = _asset_progress(progress, asset.id)
            asset_progress["status"] = "preprocessing"
            await self._persist_job_phase(session, job, "extracting_frames", progress=progress)
            if not asset.storage_path:
                asset.status = "failed"
                asset_progress.update({"status": "failed", "error": "raw media file is missing"})
                await self._persist_job_phase(session, job, "extracting_frames", progress=progress)
                continue
            existing_frame_count = _asset_frame_count(asset)
            if asset.status == "ready" and existing_frame_count:
                metadata = dict(asset.metadata_ or {})
                asset_progress.update(
                    {
                        "status": "ready",
                        "frame_total": existing_frame_count,
                        "frame_analyzed": int(asset_progress.get("frame_analyzed") or 0),
                        "asr_status": _existing_asr_status(metadata),
                        "error": metadata.get("preprocess_warning") or "",
                    }
                )
                self._update_frame_progress_from_assets(progress)
                await self._persist_job_phase(session, job, "extracting_frames", progress=progress)
                continue
            preprocessed = await asyncio.to_thread(
                self.preprocessor.preprocess,
                asset_id=asset.id,
                media_type=asset.media_type,
                storage_path=str(asset.storage_path),
                mime_type=asset.mime_type,
            )
            metadata = {**(asset.metadata_ or {}), **dict(preprocessed.get("metadata") or {})}
            asset.preview_refs = list(preprocessed.get("preview_refs") or [])
            asset.status = str(preprocessed.get("status") or "ready")
            asset.width = _optional_int(metadata.get("width"))
            asset.height = _optional_int(metadata.get("height"))
            asset.duration_seconds = _optional_float(metadata.get("duration_seconds"))
            asset.metadata_ = metadata
            frame_count = sum(1 for ref in asset.preview_refs if isinstance(ref, dict) and ref.get("kind") in VISUAL_PREVIEW_KINDS)
            asset_progress.update(
                {
                    "status": "ready" if asset.status == "ready" else asset.status,
                    "frame_total": frame_count,
                    "frame_analyzed": 0,
                    "asr_status": "pending" if metadata.get("audio_refs") else "not_applicable",
                    "error": metadata.get("preprocess_warning") or "",
                }
            )
            self._update_frame_progress_from_assets(progress)
            await self._persist_job_phase(session, job, "extracting_frames", progress=progress)

    async def _transcribe_assets(
        self,
        session: AsyncSession,
        *,
        job: MediaAnalysisJob,
        assets: list[MediaAsset],
        progress: dict[str, Any],
        include_audio: bool,
    ) -> list[dict[str, Any]]:
        if not include_audio:
            return []
        transcripts: list[dict[str, Any]] = []
        for asset in assets:
            asset_progress = _asset_progress(progress, asset.id)
            metadata = dict(asset.metadata_ or {})
            audio_refs = metadata.get("audio_refs") if isinstance(metadata.get("audio_refs"), list) else []
            if not audio_refs:
                continue
            existing_transcripts = metadata.get("audio_transcripts") if isinstance(metadata.get("audio_transcripts"), list) else []
            if existing_transcripts:
                transcripts.extend(existing_transcripts)
                asset_progress["asr_status"] = _transcript_status(existing_transcripts)
                await self._persist_job_phase(session, job, "transcribing_audio", progress=progress)
                continue
            asset_progress["asr_status"] = "running"
            await self._persist_job_phase(session, job, "transcribing_audio", progress=progress)
            asset_transcripts: list[dict[str, Any]] = []
            for audio_ref in audio_refs:
                transcript = await self.asr.transcribe(audio_ref)
                asset_transcripts.append(transcript)
                transcripts.append(transcript)
            metadata["audio_transcripts"] = asset_transcripts
            asset.metadata_ = metadata
            if any(row.get("status") == "completed" for row in asset_transcripts):
                asset_progress["asr_status"] = "completed"
            elif all(row.get("status") == "skipped_no_api_key" for row in asset_transcripts):
                asset_progress["asr_status"] = "skipped_no_api_key"
            elif any(row.get("status") == "rate_limited_failed" for row in asset_transcripts):
                asset_progress["asr_status"] = "rate_limited_failed"
                asset_progress["status"] = "failed"
                asset_progress["error"] = "audio transcription rate limit retry budget exhausted"
            else:
                asset_progress["asr_status"] = "failed"
                asset_progress["status"] = "failed"
                asset_progress["error"] = asset_progress.get("error") or "audio transcription failed"
            await self._persist_job_phase(session, job, "transcribing_audio", progress=progress)
        return transcripts

    async def _analyze_frame_batches(
        self,
        *,
        session: AsyncSession,
        job: MediaAnalysisJob,
        assets: list[MediaAsset],
        frames: list[dict[str, Any]],
        setup: dict[str, Any],
        target_child_hint: dict[str, Any] | None,
        progress: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], list[str]]:
        if not frames:
            result, raw = await self.vision.analyze(assets=assets, structured_setup=setup, target_child_hint=target_child_hint, include_audio=True)
            await self._persist_job_phase(session, job, "analyzing_frames", progress=progress)
            return [result], [raw]
        batch_size = max(1, int(self.settings.multimodal_frame_batch_size))
        batch_results: list[dict[str, Any]] = []
        raw_batches: list[str] = []
        already_analyzed = int(_as_dict(progress.get("frame_progress")).get("analyzed") or 0)
        for batch_index, start in enumerate(range(0, len(frames), batch_size), start=1):
            batch_frames = frames[start : start + batch_size]
            if start + len(batch_frames) <= already_analyzed:
                continue
            batch_assets = _assets_for_frame_batch(assets, batch_frames)
            frame_progress = _as_dict(progress.get("frame_progress"))
            frame_progress["current_batch"] = batch_index
            frame_progress["total_batches"] = (len(frames) + batch_size - 1) // batch_size
            progress["frame_progress"] = frame_progress
            await self._persist_job_phase(session, job, "analyzing_frames", progress=progress)
            result, raw = await self.vision.analyze(assets=batch_assets, structured_setup=setup, target_child_hint=target_child_hint, include_audio=False)
            batch_results.append(result)
            raw_batches.append(raw)
            for frame in batch_frames:
                asset_id = str(frame.get("asset_id"))
                asset_progress = _asset_progress(progress, asset_id)
                asset_progress["frame_analyzed"] = int(asset_progress.get("frame_analyzed") or 0) + 1
                batches = list(asset_progress.get("contribution_batches") or [])
                if batch_index not in batches:
                    batches.append(batch_index)
                asset_progress["contribution_batches"] = batches
            frame_progress = _as_dict(progress.get("frame_progress"))
            frame_progress["analyzed"] = int(frame_progress.get("analyzed") or 0) + len(batch_frames)
            frame_progress["pending"] = max(0, int(frame_progress.get("total") or 0) - int(frame_progress.get("analyzed") or 0))
            progress["frame_progress"] = frame_progress
            await self._persist_job_phase(session, job, "analyzing_frames", progress=progress)
        return batch_results, raw_batches

    async def _draft_for_job(self, session: AsyncSession, job_id: str) -> ChildMultimodalObservationDraft | None:
        drafts = await self._drafts_for_job(session, job_id)
        return drafts[0] if drafts else None

    async def _drafts_for_job(self, session: AsyncSession, job_id: str) -> list[ChildMultimodalObservationDraft]:
        return (
            await session.execute(
                select(ChildMultimodalObservationDraft)
                .where(ChildMultimodalObservationDraft.analysis_job_id == job_id)
                .order_by(ChildMultimodalObservationDraft.created_at.desc(), ChildMultimodalObservationDraft.id.desc())
            )
        ).scalars().all()

    def _set_job_phase(self, job: MediaAnalysisJob, phase: str, *, progress: dict[str, Any]) -> None:
        progress["phase"] = phase
        job.normalized_result = {**(job.normalized_result or {}), **progress}

    async def _persist_job_phase(self, session: AsyncSession, job: MediaAnalysisJob, phase: str, *, progress: dict[str, Any]) -> None:
        self._set_job_phase(job, phase, progress=progress)
        await session.flush()
        await session.commit()

    async def _record_analysis_failure(self, session: AsyncSession, *, job_id: str, actor: str, error: Exception) -> None:
        await session.rollback()
        job = await session.get(MediaAnalysisJob, job_id)
        if job is None:
            return
        progress = _job_progress(job)
        job.status = "failed"
        job.error_message = str(error)
        self._set_job_phase(job, "failed", progress=progress)
        job.completed_at = datetime.now(UTC)
        self._audit(
            session,
            actor=actor,
            action="child_observation.analysis.failed",
            target_type="media_analysis_job",
            target_id=job.id,
            payload={"error": job.error_message[:300]},
        )
        await session.flush()
        await session.commit()

    def _update_frame_progress_from_assets(self, progress: dict[str, Any]) -> None:
        frame_progress = _as_dict(progress.get("frame_progress"))
        analyzed = int(frame_progress.get("analyzed") or 0)
        total = sum(int(_as_dict(row).get("frame_total") or 0) for row in _as_dict(progress.get("asset_progress")).values())
        progress["frame_progress"] = {
            **frame_progress,
            "total": total,
            "analyzed": analyzed,
            "failed": int(frame_progress.get("failed") or 0),
            "pending": max(0, total - analyzed),
        }

    async def get_job_draft_id(self, session: AsyncSession, job_id: str) -> str | None:
        draft = await self._draft_for_job(session, job_id)
        return draft.id if draft else None

    async def get_draft(self, session: AsyncSession, draft_id: str) -> ChildMultimodalObservationDraft:
        draft = await session.get(ChildMultimodalObservationDraft, draft_id)
        if draft is None:
            raise ValueError("observation draft not found")
        return draft

    def generated_child_description_for_draft(self, draft: ChildMultimodalObservationDraft) -> str:
        existing = str(draft.generated_child_description or "").strip()
        if existing:
            return existing
        setup = ChildObservationStructuredSetup.model_validate(_as_dict(draft.structured_setup))
        result = {
            "target_child": _as_dict(draft.target_child),
            "observable_summary": draft.observable_summary,
            "visible_observations": list(draft.visible_observations or []),
            "audio_observations": list(draft.audio_observations or []),
            "behavior_signals": list(draft.behavior_signals or []),
            "temperament_hypotheses": list(draft.temperament_hypotheses or []),
            "interests": list(draft.interests or []),
            "development_hints": _as_dict(draft.development_hints),
            "initial_memory_candidates": list(draft.initial_memory_candidates or []),
            "unknowns": list(draft.unknowns or []),
        }
        return self._build_sectioned_child_description("", setup=setup, result=result)

    async def get_draft_preview_refs(self, session: AsyncSession, draft: ChildMultimodalObservationDraft) -> list[dict[str, Any]]:
        job = await session.get(MediaAnalysisJob, draft.analysis_job_id)
        if job is None:
            return []
        assets = await self._load_assets(session, list(job.asset_ids or []), allow_missing=True)
        preview_refs: list[dict[str, Any]] = []
        for asset in assets:
            preview_refs.extend(asset.preview_refs or [])
            metadata = asset.metadata_ or {}
            audio_refs = metadata.get("audio_refs") if isinstance(metadata, dict) else None
            if isinstance(audio_refs, list):
                preview_refs.extend(audio_refs)
        return preview_refs

    async def review_draft(
        self,
        session: AsyncSession,
        *,
        draft: ChildMultimodalObservationDraft,
        payload: ObservationReviewRequest,
        actor: str,
    ) -> dict[str, Any]:
        if draft.status in {"rejected", "converted"}:
            raise ValueError("observation draft cannot be reviewed in its current status")
        self._assert_review_authorized(draft, payload.authorization_confirmation, actor)
        target_child = dict(draft.target_child or {})
        if payload.target_child_confirmation.confirmed:
            target_child["operator_confirmed"] = True
        if payload.target_child_confirmation.operator_override:
            target_child["operator_override"] = payload.target_child_confirmation.operator_override
            target_child["operator_confirmed"] = True
        if self._target_requires_confirmation(target_child) and not target_child.get("operator_confirmed"):
            raise ValueError("target child must be confirmed before retaining target-specific observations")
        approved_items = self._apply_review_decisions(session, draft, payload.decisions)
        approved_payload = self._build_approved_payload(draft, approved_items, target_child)
        draft.target_child = target_child
        draft.authorization_confirmation = payload.authorization_confirmation.model_dump(mode="json")
        draft.approved_payload = approved_payload
        draft.status = "approved"
        self._audit(
            session,
            actor=actor,
            action="child_observation.review.approve",
            target_type="child_multimodal_observation_draft",
            target_id=draft.id,
            payload={"decision_count": len(payload.decisions), "target_confirmed": target_child.get("operator_confirmed", False)},
        )
        raw_media_deleted = await self.delete_draft_media(session, draft=draft, actor=actor, reason="confirmed")
        await session.flush()
        return {"approved_payload": approved_payload, "raw_media_deleted": raw_media_deleted}

    async def accept_child_description(
        self,
        session: AsyncSession,
        *,
        draft: ChildMultimodalObservationDraft,
        payload: ObservationDescriptionAcceptRequest,
        actor: str,
    ) -> dict[str, Any]:
        if draft.status in {"rejected", "converted"}:
            raise ValueError("observation draft cannot accept a description in its current status")
        description = payload.description.strip()
        if not description:
            raise ValueError("accepted child description is required")
        description_risk_flags = self._risk_flags(description)
        self._assert_description_authorized(draft, description_risk_flags, payload.authorization_confirmation, actor)
        approved_payload = self._build_description_payload(draft, description, description_risk_flags)
        draft.accepted_child_description = description
        draft.authorization_confirmation = payload.authorization_confirmation.model_dump(mode="json")
        draft.approved_payload = approved_payload
        draft.status = "description_accepted"
        self._audit(
            session,
            actor=actor,
            action="child_observation.description.accept",
            target_type="child_multimodal_observation_draft",
            target_id=draft.id,
            payload={"description_length": len(description), "risk_flag_count": len(description_risk_flags)},
        )
        raw_media_deleted = await self.delete_draft_media(session, draft=draft, actor=actor, reason="description_accepted")
        await session.flush()
        return {"approved_payload": approved_payload, "raw_media_deleted": raw_media_deleted, "risk_flags": description_risk_flags}

    async def reject_draft(
        self,
        session: AsyncSession,
        *,
        draft: ChildMultimodalObservationDraft,
        reason: str,
        actor: str,
    ) -> bool:
        draft.status = "rejected"
        draft.rejected_reason = reason
        self._audit(
            session,
            actor=actor,
            action="child_observation.review.reject",
            target_type="child_multimodal_observation_draft",
            target_id=draft.id,
            payload={"reason": reason},
        )
        deleted = await self.delete_draft_media(session, draft=draft, actor=actor, reason="rejected")
        await session.flush()
        return deleted

    async def delete_analysis_history(
        self,
        session: AsyncSession,
        *,
        job: MediaAnalysisJob,
        actor: str,
    ) -> dict[str, Any]:
        if job.status in {"queued", "running"}:
            raise ValueError("active analysis jobs cannot be deleted")
        drafts = await self._drafts_for_job(session, job.id)
        if any(draft.status in {"approved", "description_accepted", "converted"} or draft.child_world_draft_id for draft in drafts):
            raise ValueError("submitted observation drafts cannot be deleted from history")
        deleted_asset_ids: list[str] = []
        for asset in await self._load_assets(session, list(job.asset_ids or []), allow_missing=True):
            if asset.status != "deleted":
                await self.delete_media(session, asset=asset, actor=actor, reason="history_deleted")
            deleted_asset_ids.append(asset.id)
        draft_id = drafts[0].id if drafts else None
        self._audit(
            session,
            actor=actor,
            action="child_observation.analysis.delete",
            target_type="media_analysis_job",
            target_id=job.id,
            payload={
                "draft_id": draft_id,
                "draft_ids": [draft.id for draft in drafts],
                "job_status": job.status,
                "asset_count": len(deleted_asset_ids),
            },
        )
        for draft in drafts:
            await session.delete(draft)
        await session.delete(job)
        await session.flush()
        return {
            "id": job.id,
            "observation_draft_id": draft_id,
            "raw_media_deleted": bool(deleted_asset_ids),
            "deleted_asset_ids": deleted_asset_ids,
        }

    async def delete_media(self, session: AsyncSession, *, asset: MediaAsset, actor: str, reason: str) -> MediaAsset:
        metadata = asset.metadata_ or {}
        extra_refs = metadata.get("audio_refs") if isinstance(metadata, dict) else []
        self.storage.delete_paths(asset.storage_path, list(asset.preview_refs or []) + list(extra_refs or []))
        asset.storage_path = None
        asset.preview_refs = []
        asset.status = "deleted"
        asset.deletion_reason = reason
        asset.deleted_at = datetime.now(UTC)
        self._audit(
            session,
            actor=actor,
            action="child_observation.media.delete",
            target_type="media_asset",
            target_id=asset.id,
            payload={"reason": reason},
        )
        await session.flush()
        return asset

    async def delete_draft_media(
        self,
        session: AsyncSession,
        *,
        draft: ChildMultimodalObservationDraft,
        actor: str,
        reason: str,
    ) -> bool:
        job = await session.get(MediaAnalysisJob, draft.analysis_job_id)
        if job is None:
            return False
        assets = await self._load_assets(session, list(job.asset_ids or []), allow_missing=True)
        for asset in assets:
            if asset.status != "deleted":
                await self.delete_media(session, asset=asset, actor=actor, reason=reason)
        draft.raw_media_deleted_at = datetime.now(UTC)
        return True

    async def convert_to_child_world_draft(
        self,
        session: AsyncSession,
        *,
        draft: ChildMultimodalObservationDraft,
        actor: str,
    ) -> ChildWorldDraft:
        if draft.status not in {"approved", "converted", "description_accepted"}:
            raise ValueError("observation draft must be approved before conversion")
        if draft.child_world_draft_id:
            existing = await session.get(ChildWorldDraft, draft.child_world_draft_id)
            if existing is not None:
                return existing
        approved_payload = dict(draft.approved_payload or {})
        child_request = self._child_world_request_from_payload(draft, approved_payload)
        child_world_draft = await ChildWorldDraftService().create_draft(session, child_request)
        child_world_draft.input_params = {
            **(child_world_draft.input_params or {}),
            "observation_provenance": {
                "observation_draft_id": draft.id,
                "analysis_job_id": draft.analysis_job_id,
                "risk_flags": draft.risk_flags,
                "target_child": draft.target_child,
            },
        }
        draft.child_world_draft_id = child_world_draft.id
        draft.status = "converted"
        self._audit(
            session,
            actor=actor,
            action="child_observation.convert",
            target_type="child_multimodal_observation_draft",
            target_id=draft.id,
            payload={"child_world_draft_id": child_world_draft.id},
        )
        await session.flush()
        return child_world_draft

    def asset_states(self, job: MediaAnalysisJob) -> AssetStates:
        return AssetStates(
            analyzed=list(job.analyzed_asset_ids or []),
            pending=list(job.pending_asset_ids or []),
            skipped=list(job.skipped_asset_ids or []),
            excluded=list(job.excluded_asset_ids or []),
        )

    async def _load_assets(self, session: AsyncSession, asset_ids: list[str], *, allow_missing: bool = False) -> list[MediaAsset]:
        if not asset_ids:
            return []
        assets = (await session.execute(select(MediaAsset).where(MediaAsset.id.in_(asset_ids)))).scalars().all()
        by_id = {asset.id: asset for asset in assets}
        missing = [asset_id for asset_id in asset_ids if asset_id not in by_id]
        if missing and not allow_missing:
            raise ValueError(f"media asset not found: {missing[0]}")
        return [by_id[asset_id] for asset_id in asset_ids if asset_id in by_id]

    def _normalize_observation_result(
        self,
        result: dict[str, Any],
        *,
        setup: ChildObservationStructuredSetup,
        assets: list[MediaAsset],
        include_audio: bool,
    ) -> dict[str, Any]:
        fallback_ref = self._fallback_evidence_ref(assets)
        normalized = dict(result)
        target_child = self._normalize_target_child(normalized.get("target_child"), fallback_ref)
        normalized["target_child"] = target_child
        for field in REVIEW_LIST_FIELDS:
            normalized[field] = [
                self._normalize_statement(item, fallback_ref=fallback_ref)
                for item in _as_list(normalized.get(field))
            ]
        if not include_audio:
            normalized["audio_observations"] = []
        normalized["development_hints"] = self._normalize_development_hints(normalized.get("development_hints"), fallback_ref)
        normalized["avatar_brief"] = _as_dict(normalized.get("avatar_brief"))
        normalized["observable_summary"] = str(normalized.get("observable_summary") or "媒体观察草稿已生成，需人工审核。")
        if self._confidence_band(target_child.get("confidence", 0)) == "low":
            normalized["temperament_hypotheses"] = []
            normalized["interests"] = []
            normalized["development_hints"] = {}
            normalized["initial_memory_candidates"] = []
            normalized["unknowns"] = list(normalized.get("unknowns") or []) + ["目标儿童置信度低，仅保留场景或互动层观察。"]
        normalized["generated_child_description"] = self._build_sectioned_child_description(
            normalized.get("generated_child_description"),
            setup=setup,
            result=normalized,
        )
        normalized["accepted_child_description"] = str(normalized.get("accepted_child_description") or "")
        normalized["risk_flags"] = self._risk_flags(
            setup.natural_language_prompt,
            normalized["generated_child_description"],
            json.dumps(normalized, ensure_ascii=False),
        )
        return normalized

    def _draft_from_result(
        self,
        *,
        job: MediaAnalysisJob,
        setup: ChildObservationStructuredSetup,
        result: dict[str, Any],
    ) -> ChildMultimodalObservationDraft:
        return ChildMultimodalObservationDraft(
            status="in_review",
            analysis_job_id=job.id,
            structured_setup=setup.model_dump(),
            target_child=result.get("target_child") or {},
            observable_summary=str(result.get("observable_summary") or ""),
            generated_child_description=str(result.get("generated_child_description") or ""),
            accepted_child_description=str(result.get("accepted_child_description") or ""),
            visible_observations=list(result.get("visible_observations") or []),
            audio_observations=list(result.get("audio_observations") or []),
            non_identifying_appearance=list(result.get("non_identifying_appearance") or []),
            behavior_signals=list(result.get("behavior_signals") or []),
            temperament_hypotheses=list(result.get("temperament_hypotheses") or []),
            interests=list(result.get("interests") or []),
            development_hints=_as_dict(result.get("development_hints")),
            avatar_brief=_as_dict(result.get("avatar_brief")),
            initial_memory_candidates=list(result.get("initial_memory_candidates") or []),
            unknowns=list(result.get("unknowns") or []),
            risk_flags=list(result.get("risk_flags") or []),
        )

    def _normalize_target_child(self, value: Any, fallback_ref: str) -> dict[str, Any]:
        row = _as_dict(value)
        confidence = _clamp_float(row.get("confidence"), default=0)
        return {
            "description": str(row.get("description") or "媒体中的目标儿童"),
            "confidence": confidence,
            "confidence_band": self._confidence_band(confidence),
            "evidence_refs": _text_refs(row.get("evidence_refs"), fallback_ref),
            "operator_confirmed": bool(row.get("operator_confirmed", False)),
            "operator_override": row.get("operator_override"),
        }

    def _normalize_statement(self, item: Any, *, fallback_ref: str) -> dict[str, Any]:
        row = _as_dict(item)
        content = str(row.get("content") or row.get("text") or row.get("summary") or item or "").strip()
        return {
            **row,
            "content": content or "未命名观察项",
            "confidence": _clamp_float(row.get("confidence"), default=0.5),
            "evidence_refs": _text_refs(row.get("evidence_refs"), fallback_ref),
        }

    def _normalize_development_hints(self, value: Any, fallback_ref: str) -> dict[str, Any]:
        hints = _as_dict(value)
        normalized: dict[str, Any] = {}
        for key, rows in hints.items():
            normalized[key] = [self._normalize_statement(row, fallback_ref=fallback_ref) for row in _as_list(rows)]
        return normalized

    def _normalize_generated_child_description(
        self,
        value: Any,
        *,
        setup: ChildObservationStructuredSetup,
        result: dict[str, Any],
    ) -> str:
        existing = str(value or "").strip()
        if existing:
            return existing
        child_name = setup.child_display_name or "孩子"
        age_text = f"约 {setup.age_months} 个月"
        target = _as_dict(result.get("target_child"))
        low_confidence = self._confidence_band(target.get("confidence", 0)) == "low"
        parts = [f"{child_name}是一名{age_text}的儿童。"]
        summary = str(result.get("observable_summary") or "").strip()
        if summary:
            parts.append(_strip_review_language(summary))
        parts.extend(self._statement_contents(result, "visible_observations", limit=2))
        parts.extend(self._statement_contents(result, "audio_observations", limit=1))
        parts.extend(self._statement_contents(result, "behavior_signals", limit=2))
        if not low_confidence:
            parts.extend(self._statement_contents(result, "interests", limit=2, prefix="可能的兴趣线索："))
            parts.extend(self._statement_contents(result, "temperament_hypotheses", limit=1, prefix="气质线索："))
            parts.extend(self._development_hint_contents(result, limit=2))
            parts.extend(self._statement_contents(result, "initial_memory_candidates", limit=1, prefix="可作为初始经历素材："))
        else:
            parts.append("由于媒体中目标儿童区分度较低，描述仅保留场景和互动层信息，不写入稳定特质、发展结论或初始记忆。")
        unknowns = [
            safe
            for safe in (
                _strip_review_language(str(_as_dict(item).get("content") or _as_dict(item).get("text") or _as_dict(item).get("summary") or item))
                for item in _as_list(result.get("unknowns"))
            )
            if safe
        ]
        if unknowns:
            parts.append(f"仍未知或不应推断：{'；'.join(unknowns[:2])}。")
        return _compact_description(parts)

    def _statement_contents(self, result: dict[str, Any], field: str, *, limit: int, prefix: str = "") -> list[str]:
        contents: list[str] = []
        for item in _as_list(result.get(field)):
            content = _strip_review_language(str(_as_dict(item).get("content") or item or ""))
            if not content:
                continue
            contents.append(f"{prefix}{content}" if prefix else content)
            if len(contents) >= limit:
                break
        return contents

    def _development_hint_contents(self, result: dict[str, Any], *, limit: int) -> list[str]:
        contents: list[str] = []
        for rows in _as_dict(result.get("development_hints")).values():
            for item in _as_list(rows):
                content = _strip_review_language(str(_as_dict(item).get("content") or item or ""))
                if content:
                    contents.append(f"发展观察线索：{content}")
                if len(contents) >= limit:
                    return contents
        return contents

    def _build_sectioned_child_description(
        self,
        value: Any,
        *,
        setup: ChildObservationStructuredSetup,
        result: dict[str, Any],
    ) -> str:
        existing = str(value or "").strip()
        if _description_is_user_ready(existing):
            return existing[:6000]

        child_name = setup.child_display_name or "孩子"
        age_text = f"约 {setup.age_months} 个月" if setup.age_months else "当前阶段"
        target = _as_dict(result.get("target_child"))
        low_confidence = self._confidence_band(target.get("confidence", 0)) == "low"
        visible = self._clean_statement_contents(result, "visible_observations", limit=4)
        behavior = self._clean_statement_contents(result, "behavior_signals", limit=4)
        interests = self._clean_statement_contents(result, "interests", limit=4)
        temperament = self._clean_statement_contents(result, "temperament_hypotheses", limit=3)
        development = self._clean_development_hint_contents(result, limit=4)
        memories = self._clean_statement_contents(result, "initial_memory_candidates", limit=2)
        unknowns = _unknown_contents(result, limit=4)
        summary = _safe_observation_text({"content": result.get("observable_summary")})

        confidence_note = (
            "由于媒体中目标儿童区分度较低，以下内容只保留场景、活动和互动层面的弱观察线索。"
            if low_confidence
            else "以下内容主要基于上传媒体中的可见画面归纳，音频仅作为弱辅助背景。"
        )
        movement_text = _join_clauses(
            [*behavior[:2], *visible[:1]],
            default="画面可继续用于提取走动、停留、姿态变化、参与活动等大运动线索；当前不据此判断长期能力。",
        )
        fine_motor_text = _join_clauses(
            [*interests[:1], *behavior[2:4]],
            default="可从接触物件、拿取、推动、摆弄、装倒等动作中继续确认精细操作和探索方式。",
        )
        caregiver_text = _join_clauses(
            [*temperament[:1], *development[:1]],
            default="若画面中出现成人陪伴、牵引、抱持或回应，可作为亲子互动和安全感来源的观察线索。",
        )
        emotion_text = _join_clauses(
            visible[1:3],
            default="情绪状态需从连续画面中确认；仅可保守观察是否存在安静、专注、笑容、抗拒或哭闹等可见表现。",
        )
        social_text = _join_clauses(
            development[1:3],
            default="同伴互动、并行游戏或合作游戏需要更长连续片段确认，当前只作为社交方式候选线索。",
        )
        interest_text = _join_clauses(
            interests[:3],
            default="兴趣画像应来自反复出现的活动、玩具、自然材料、互动装置或可操作物件。",
        )
        memory_text = _join_clauses(
            memories[:1],
            default="可把媒体中的一次真实活动片段作为初始经历素材，但细节需要继续审核确认。",
        )
        boundary_text = _join_clauses(
            unknowns,
            default="无法从媒体可靠判断长期能力、家庭背景、稳定人格、医学或心理诊断，也不能进行身份识别或声纹识别。",
        )
        summary_line = f"   媒体摘要：{summary}\n" if summary else ""

        description = (
            "当前儿童的主要特征\n\n"
            f"1. {child_name}是一名{age_text}的儿童，{confidence_note}\n"
            f"{summary_line}"
            f"2. 活动与动作线索：{movement_text}\n"
            f"3. 操作与探索兴趣：{fine_motor_text}\n"
            f"4. 亲子互动与安全感线索：{caregiver_text}\n"
            f"5. 情绪与参与状态：{emotion_text}\n"
            f"6. 社交与环境适应：{social_text}\n"
            f"7. 当前兴趣画像：{interest_text}\n\n"
            "简要画像\n\n"
            f"{child_name}当前更适合被描述为一个需要结合多段真实画面继续确认的观察对象。"
            f"已有线索显示，可以从活动参与、物件操作、照护者互动、环境适应和兴趣偏好中提炼儿童特征。{memory_text}\n\n"
            "观察边界\n\n"
            f"{boundary_text}"
        )
        return description[:6000]

    def _clean_statement_contents(self, result: dict[str, Any], field: str, *, limit: int) -> list[str]:
        contents: list[str] = []
        for item in _as_list(result.get(field)):
            content = _safe_observation_text(item)
            if not content:
                continue
            contents.append(content)
            if len(contents) >= limit:
                break
        return contents

    def _clean_development_hint_contents(self, result: dict[str, Any], *, limit: int) -> list[str]:
        contents: list[str] = []
        for rows in _as_dict(result.get("development_hints")).values():
            for item in _as_list(rows):
                content = _safe_observation_text(item)
                if content:
                    contents.append(content)
                if len(contents) >= limit:
                    return contents
        return contents

    def _risk_flags(self, *parts: str) -> list[dict[str, Any]]:
        text = "\n".join(part for part in parts if part)
        flags: list[dict[str, Any]] = []
        for category, pattern in PROHIBITED_PATTERNS:
            if _contains_unnegated_policy_match(text, pattern):
                flags.append({"category": category, "severity": "prohibited", "message": "禁止的身份、诊断、智力或外貌/声音推断"})
        for category, pattern in HIGH_RISK_PATTERNS:
            if re.search(pattern, text, flags=re.IGNORECASE):
                flags.append({"category": category, "severity": "high", "message": "需要额外授权确认后才能继续"})
        return flags

    def _assert_review_authorized(self, draft: ChildMultimodalObservationDraft, authorization: AuthorizationConfirmation, actor: str) -> None:
        risk_flags = list(draft.risk_flags or [])
        if any(_as_dict(flag).get("severity") == "prohibited" for flag in risk_flags):
            raise ValueError("draft contains prohibited claims that cannot be authorized")
        has_high_risk = any(_as_dict(flag).get("severity") == "high" for flag in risk_flags)
        if has_high_risk and not authorization.confirmed:
            raise ValueError("high-risk observation draft requires additional authorization")
        if authorization.confirmed:
            authorization.confirmed_by = authorization.confirmed_by or actor
            authorization.confirmed_at = authorization.confirmed_at or datetime.now(UTC)

    def _assert_description_authorized(
        self,
        draft: ChildMultimodalObservationDraft,
        description_risk_flags: list[dict[str, Any]],
        authorization: AuthorizationConfirmation,
        actor: str,
    ) -> None:
        draft_risk_flags = list(draft.risk_flags or [])
        all_flags = [*_as_list(draft_risk_flags), *description_risk_flags]
        if any(_as_dict(flag).get("severity") == "prohibited" for flag in all_flags):
            raise ValueError("description contains prohibited claims that cannot be authorized")
        has_high_risk_description = any(_as_dict(flag).get("severity") == "high" for flag in description_risk_flags)
        if has_high_risk_description and not authorization.confirmed:
            raise ValueError("high-risk child description requires additional authorization")
        if authorization.confirmed:
            authorization.confirmed_by = authorization.confirmed_by or actor
            authorization.confirmed_at = authorization.confirmed_at or datetime.now(UTC)

    def _target_requires_confirmation(self, target_child: dict[str, Any]) -> bool:
        return self._confidence_band(target_child.get("confidence", 0)) in {"medium", "high"}

    def _confidence_band(self, value: Any) -> str:
        confidence = _clamp_float(value, default=0)
        if confidence >= self.settings.multimodal_target_confidence_high:
            return "high"
        if confidence >= self.settings.multimodal_target_confidence_medium:
            return "medium"
        return "low"

    def _apply_review_decisions(
        self,
        session: AsyncSession,
        draft: ChildMultimodalObservationDraft,
        decisions: list[ObservationReviewItem],
    ) -> list[dict[str, Any]]:
        approved: list[dict[str, Any]] = []
        for decision in decisions:
            original = self._value_at_path(draft, decision.item_path)
            final_value = decision.final_value if decision.final_value is not None else original
            final_row = self._final_review_value(final_value, original)
            if decision.decision in {"approved", "edited"}:
                approved.append({"item_path": decision.item_path, "value": final_row})
            elif decision.decision in {"downgraded", "unknown"}:
                unknown = {"content": final_row.get("content") or "审核者降级为未知项", "confidence": final_row.get("confidence", 0), "evidence_refs": final_row.get("evidence_refs", [])}
                draft.unknowns = list(draft.unknowns or []) + [unknown]
            session.add(
                ObservationReviewDecision(
                    observation_draft_id=draft.id,
                    item_path=decision.item_path,
                    decision=decision.decision,
                    original_value=_as_dict(original),
                    final_value=final_row,
                    confidence=_optional_float(final_row.get("confidence")),
                    evidence_refs=list(final_row.get("evidence_refs") or []),
                    rationale=decision.rationale,
                )
            )
        if not decisions:
            for field in ("visible_observations", "audio_observations", "behavior_signals", "interests", "initial_memory_candidates"):
                for index, item in enumerate(_as_list(getattr(draft, field))):
                    approved.append({"item_path": f"{field}[{index}]", "value": _as_dict(item)})
        return approved

    def _final_review_value(self, final_value: Any, original: Any) -> dict[str, Any]:
        if isinstance(final_value, str):
            base = _as_dict(original)
            base["content"] = final_value
            return base
        row = _as_dict(final_value) or _as_dict(original)
        fallback_ref = "text:review"
        row["content"] = str(row.get("content") or row.get("text") or row)
        row["confidence"] = _clamp_float(row.get("confidence"), default=_clamp_float(_as_dict(original).get("confidence"), default=0.5))
        row["evidence_refs"] = _text_refs(row.get("evidence_refs"), fallback_ref)
        return row

    def _value_at_path(self, draft: ChildMultimodalObservationDraft, path: str) -> Any:
        match = re.fullmatch(r"([A-Za-z_]+)\[(\d+)\]", path)
        if match:
            field, index_text = match.groups()
            values = _as_list(getattr(draft, field, []))
            index = int(index_text)
            if 0 <= index < len(values):
                return values[index]
            return {}
        if "." in path:
            head, _, tail = path.partition(".")
            current = getattr(draft, head, {})
            for part in tail.split("."):
                current = _as_dict(current).get(part, {})
            return current
        return getattr(draft, path, {})

    def _build_approved_payload(
        self,
        draft: ChildMultimodalObservationDraft,
        approved_items: list[dict[str, Any]],
        target_child: dict[str, Any],
    ) -> dict[str, Any]:
        setup = _as_dict(draft.structured_setup)
        approved_texts = [str(_as_dict(item.get("value")).get("content") or "") for item in approved_items]
        evidence_refs = sorted(
            {
                str(ref)
                for item in approved_items
                for ref in _as_list(_as_dict(item.get("value")).get("evidence_refs"))
                if isinstance(ref, str)
            }
        )
        prompt = "\n".join(
            part
            for part in [
                "以下内容来自经过人工审核的多模态儿童观察草稿，只能作为儿童世界初始化参考。",
                f"观察摘要：{draft.observable_summary}",
                f"目标儿童：{target_child.get('operator_override') or target_child.get('description', '')}",
                "已批准观察：",
                *[f"- {text}" for text in approved_texts if text],
                f"证据引用：{', '.join(evidence_refs) if evidence_refs else 'text:review'}",
                f"风险标记：{json.dumps(draft.risk_flags, ensure_ascii=False)}",
            ]
            if part
        )
        return {
            "structured_setup": setup,
            "child_display_name": setup.get("child_display_name") or setup.get("child_name"),
            "natural_language_prompt": prompt,
            "approved_items": approved_items,
            "evidence_refs": evidence_refs,
            "target_child": target_child,
            "risk_flags": draft.risk_flags,
        }

    def _build_description_payload(
        self,
        draft: ChildMultimodalObservationDraft,
        description: str,
        description_risk_flags: list[dict[str, Any]],
    ) -> dict[str, Any]:
        setup = _as_dict(draft.structured_setup)
        return {
            "structured_setup": setup,
            "child_display_name": setup.get("child_display_name") or setup.get("child_name"),
            "natural_language_prompt": description,
            "accepted_child_description": description,
            "generated_child_description": draft.generated_child_description,
            "target_child": draft.target_child,
            "risk_flags": description_risk_flags,
            "source_observation_draft_id": draft.id,
        }

    def _child_world_request_from_payload(self, draft: ChildMultimodalObservationDraft, approved_payload: dict[str, Any]) -> ChildWorldDraftRequest:
        setup = ChildObservationStructuredSetup.model_validate(approved_payload.get("structured_setup") or draft.structured_setup)
        return setup.to_child_world_request(
            prompt=str(approved_payload.get("natural_language_prompt") or setup.natural_language_prompt),
            source_observation_draft_id=draft.id,
        )

    def _fallback_evidence_ref(self, assets: list[MediaAsset]) -> str:
        for asset in assets:
            refs = asset.preview_refs or []
            for ref in refs:
                if isinstance(ref, dict) and ref.get("ref"):
                    return str(ref["ref"])
        return f"asset:{assets[0].id}" if assets else "text:setup"

    def _audit(self, session: AsyncSession, *, actor: str, action: str, target_type: str, target_id: str | None, payload: dict[str, Any]) -> None:
        session.add(AuditLog(actor=actor, action=action, target_type=target_type, target_id=target_id, payload=payload))


def _initial_asset_progress(assets: list[MediaAsset]) -> dict[str, Any]:
    return {
        asset.id: {
            "asset_id": asset.id,
            "filename": asset.original_filename,
            "media_type": asset.media_type,
            "status": asset.status,
            "frame_total": 0,
            "frame_analyzed": 0,
            "asr_status": "pending" if asset.media_type == "video" else "not_applicable",
            "contribution_batches": [],
            "error": "",
        }
        for asset in assets
    }


def _job_progress(job: MediaAnalysisJob) -> dict[str, Any]:
    normalized = dict(job.normalized_result or {})
    return {
        "phase": normalized.get("phase") or job.status,
        "asset_progress": _as_dict(normalized.get("asset_progress")),
        "frame_progress": _as_dict(normalized.get("frame_progress")) or {"total": 0, "analyzed": 0, "failed": 0, "pending": 0},
    }


def _asset_progress(progress: dict[str, Any], asset_id: str) -> dict[str, Any]:
    rows = progress.setdefault("asset_progress", {})
    if asset_id not in rows:
        rows[asset_id] = {
            "asset_id": asset_id,
            "status": "pending",
            "frame_total": 0,
            "frame_analyzed": 0,
            "asr_status": "pending",
            "contribution_batches": [],
            "error": "",
        }
    return rows[asset_id]


def _asset_frame_count(asset: MediaAsset) -> int:
    return sum(1 for ref in asset.preview_refs or [] if _is_visual_frame_ref(ref))


def _existing_asr_status(metadata: dict[str, Any]) -> str:
    transcripts = metadata.get("audio_transcripts") if isinstance(metadata.get("audio_transcripts"), list) else []
    if transcripts:
        return _transcript_status(transcripts)
    return "pending" if metadata.get("audio_refs") else "not_applicable"


def _transcript_status(transcripts: list[dict[str, Any]]) -> str:
    if any(row.get("status") == "completed" for row in transcripts):
        return "completed"
    if all(row.get("status") == "skipped_no_api_key" for row in transcripts):
        return "skipped_no_api_key"
    if any(row.get("status") == "rate_limited_failed" for row in transcripts):
        return "rate_limited_failed"
    return "failed"


def _frame_refs_from_assets(assets: list[MediaAsset]) -> list[dict[str, Any]]:
    frames: list[dict[str, Any]] = []
    for asset in assets:
        for ref in asset.preview_refs or []:
            if not _is_visual_frame_ref(ref):
                continue
            frame = dict(ref)
            frame["asset_id"] = asset.id
            frames.append(frame)
    return sorted(frames, key=lambda item: (str(item.get("asset_id")), float(item.get("timestamp_seconds") or 0)))


def _is_visual_frame_ref(ref: Any) -> bool:
    return isinstance(ref, dict) and ref.get("kind") in VISUAL_PREVIEW_KINDS and bool(ref.get("path"))


def _assets_for_frame_batch(assets: list[MediaAsset], frames: list[dict[str, Any]]) -> list[MediaAsset]:
    refs_by_asset: dict[str, list[dict[str, Any]]] = {}
    for frame in frames:
        refs_by_asset.setdefault(str(frame.get("asset_id")), []).append({key: value for key, value in frame.items() if key != "asset_id"})
    batch_assets: list[MediaAsset] = []
    assets_by_id = {asset.id: asset for asset in assets}
    for asset_id, refs in refs_by_asset.items():
        asset = assets_by_id.get(asset_id)
        if asset is None:
            continue
        batch_assets.append(
            MediaAsset(
                id=asset.id,
                owner_actor=asset.owner_actor,
                original_filename=asset.original_filename,
                media_type=asset.media_type,
                mime_type=asset.mime_type,
                sha256=asset.sha256,
                size_bytes=asset.size_bytes,
                storage_path=asset.storage_path,
                preview_refs=refs,
                status=asset.status,
                metadata_=asset.metadata_,
            )
        )
    return batch_assets


def _audio_summaries_from_transcripts(transcripts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for transcript in transcripts:
        has_text = bool(str(transcript.get("text") or "").strip())
        ref = str(transcript.get("ref") or "asset:unknown#audio")
        if not has_text:
            status = str(transcript.get("status") or "unknown")
            rows.append(
                {
                    "content": f"音频片段已保留为弱辅助证据，转写状态：{status}。",
                    "confidence": 0.2,
                    "evidence_refs": [ref],
                    "scope": "reviewable_audio_status",
                }
            )
            continue
        rows.append(
            {
                "content": "音频片段包含可听到的人声、音乐或互动背景，已仅作为弱辅助线索保留；最终描述不直接引用转写原文。",
                "confidence": 0.45,
                "evidence_refs": [ref],
                "scope": "reviewable_audio_summary",
                "transcript_available": True,
            }
        )
    return rows


def _audio_observations_from_transcripts(transcripts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for transcript in transcripts:
        text = str(transcript.get("text") or "").strip()
        ref = str(transcript.get("ref") or "asset:unknown#audio")
        if not text:
            status = str(transcript.get("status") or "unknown")
            rows.append(
                {
                    "content": f"音频片段已保留为证据，转写状态：{status}。",
                    "confidence": 0.2,
                    "evidence_refs": [ref],
                    "scope": "reviewable_audio_status",
                }
            )
            continue
        rows.append(
            {
                "content": text[:1200],
                "confidence": 0.55,
                "evidence_refs": [ref],
                "scope": "reviewable_audio_transcript",
            }
        )
    return rows


def _optional_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _clamp_float(value: Any, *, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    return max(0.0, min(1.0, number))


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value is None:
        return []
    return [value]


def _text_refs(value: Any, fallback_ref: str) -> list[str]:
    refs = [str(ref) for ref in _as_list(value) if isinstance(ref, str) and ref]
    return refs or [fallback_ref]


def _description_is_user_ready(text: str) -> bool:
    if not text:
        return False
    required_sections = ("当前儿童的主要特征", "简要画像", "观察边界")
    if not all(section in text for section in required_sections):
        return False
    blocked_markers = (
        "{'content'",
        '"content"',
        "evidence_refs",
        "asset:",
        "#t=",
        "transcript",
        "audio_transcripts",
        "raw_response",
        "歌词",
        "原文",
        "🎼",
    )
    return not any(marker in text for marker in blocked_markers)


def _safe_observation_text(item: Any) -> str:
    row = _as_dict(item)
    value = row.get("content") or row.get("summary") or row.get("text")
    if value is None and isinstance(item, str):
        value = item
    if isinstance(value, (dict, list, tuple, set)) or value is None:
        return ""
    text = _strip_review_language(str(value))
    if not text or _looks_internal_or_raw(text):
        return ""
    return text[:500]


def _unknown_contents(result: dict[str, Any], *, limit: int) -> list[str]:
    contents: list[str] = []
    for item in _as_list(result.get("unknowns")):
        content = _safe_observation_text(item)
        if not content:
            continue
        contents.append(content)
        if len(contents) >= limit:
            break
    return contents


def _join_clauses(values: list[str], *, default: str) -> str:
    seen: set[str] = set()
    cleaned: list[str] = []
    for value in values:
        text = _strip_review_language(value).strip()
        if not text or text in seen or _looks_internal_or_raw(text):
            continue
        seen.add(text)
        cleaned.append(text.rstrip("。；;"))
    return "；".join(cleaned) + "。" if cleaned else default


def _looks_internal_or_raw(text: str) -> bool:
    markers = (
        "{'content'",
        '"content"',
        "evidence_refs",
        "asset:",
        "#t=",
        "raw_response",
        "audio_transcripts",
        "歌词",
        "原文",
        "🎼",
    )
    if any(marker in text for marker in markers):
        return True
    return len(text) > 260 and not any(term in text for term in ("动作", "互动", "活动", "情绪", "兴趣", "场景", "成人", "照护"))


def _strip_review_language(text: str) -> str:
    cleaned = text.strip()
    replacements = (
        ("基于上传媒体生成的观察草稿：", ""),
        ("具体结论需要人工审核。", ""),
        ("需由审核者核对后保留。", ""),
        ("需要审核者确认。", ""),
        ("该项只是气质假设。", ""),
        ("但不构成发展结论。", ""),
    )
    for old, new in replacements:
        cleaned = cleaned.replace(old, new)
    return cleaned.strip(" ；;，,。")


def _compact_description(parts: list[str]) -> str:
    seen: set[str] = set()
    sentences: list[str] = []
    for part in parts:
        text = _strip_review_language(part)
        if not text or text in seen:
            continue
        seen.add(text)
        if text[-1] not in "。！？!?":
            text = f"{text}。"
        sentences.append(text)
    return "".join(sentences)[:6000]


def _contains_unnegated_policy_match(text: str, pattern: str) -> bool:
    negation_terms = (
        "cannot",
        "can't",
        "can not",
        "do not",
        "don't",
        "must not",
        "should not",
        "not infer",
        "not identify",
        "no ",
        "unable to",
        "unknown",
        "无法",
        "不能",
        "不得",
        "不可",
        "禁止",
        "不要",
        "不应",
        "未知",
        "无法判断",
    )
    negation_terms = (
        *negation_terms,
        "无法",
        "不能",
        "不得",
        "不可",
        "禁止",
        "不要",
        "不应",
        "未知",
        "无法判断",
        "不能进行",
        "不用于",
    )
    for match in re.finditer(pattern, text, flags=re.IGNORECASE):
        window = text[max(0, match.start() - 80) : min(len(text), match.end() + 80)].lower()
        if any(term in window for term in negation_terms):
            continue
        return True
    return False
