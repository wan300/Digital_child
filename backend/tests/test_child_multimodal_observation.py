import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.db.base import Base
from app.models.entities import ChildMultimodalObservationDraft, MediaAsset
from app.schemas.api import ChildObservationAnalysisJobCreate, ObservationReviewItem, ObservationReviewRequest
from app.simulation.multimodal_observation import ChildMultimodalObservationService, _frame_refs_from_assets


async def _session(tmp_path):
    settings = get_settings()
    settings.llm_api_key = ""
    settings.multimodal_api_key = ""
    settings.multimodal_base_url = ""
    settings.multimodal_allow_deterministic_fallback = True
    settings.multimodal_media_dir = tmp_path / "media"
    settings.multimodal_preview_dir = tmp_path / "media" / "previews"
    settings.multimodal_job_batch_size = 8
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'child_multimodal_service.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    return Session, engine


def test_frame_refs_ignore_metadata_only_key_frames() -> None:
    asset = MediaAsset(
        id="asset-1",
        owner_actor="admin",
        original_filename="clip.mp4",
        media_type="video",
        mime_type="video/mp4",
        sha256="x",
        size_bytes=10,
        storage_path="data/media/asset-1.mp4",
        preview_refs=[
            {"ref": "asset:asset-1#t=0s", "kind": "key_frame", "timestamp_seconds": 0},
            {
                "ref": "asset:asset-1#sheet-1",
                "kind": "contact_sheet",
                "timestamp_seconds": 1,
                "path": "data/media/previews/asset-1_sheet-001.jpg",
            },
        ],
        metadata_={},
    )

    frames = _frame_refs_from_assets([asset])

    assert len(frames) == 1
    assert frames[0]["ref"] == "asset:asset-1#sheet-1"


@pytest.mark.asyncio
async def test_analysis_retains_audio_evidence_for_video(tmp_path) -> None:
    Session, engine = await _session(tmp_path)
    async with Session() as session:
        service = ChildMultimodalObservationService()
        asset = await service.create_media_asset(
            session,
            filename="clip.mp4",
            content_type="video/mp4",
            data=b"video bytes",
            actor="admin",
        )
        audio_path = tmp_path / "audio-1.mp3"
        audio_path.write_bytes(b"audio")

        def fake_preprocess(**_kwargs):
            return {
                "status": "ready",
                "preview_refs": [],
                "metadata": {
                    "audio_track_retained": True,
                    "audio_refs": [
                        {
                            "ref": f"asset:{asset.id}#audio-1",
                            "kind": "audio_segment",
                            "path": str(audio_path),
                        }
                    ],
                },
            }

        async def fake_transcribe(audio_ref):
            return {"ref": audio_ref["ref"], "status": "failed", "text": "", "error": "ASR request failed"}

        service.preprocessor.preprocess = fake_preprocess
        service.asr.transcribe = fake_transcribe
        job, draft = await service.create_analysis_job(
            session,
            payload=ChildObservationAnalysisJobCreate(
                asset_ids=[asset.id],
                structured_setup={"child_display_name": "小雨", "age_months": 48},
                include_audio=True,
            ),
            actor="admin",
        )
        draft = await service.process_analysis_job(session, job_id=job.id, actor="admin")
        assert job.status == "partial"
        assert draft is not None
        assert asset.metadata_["audio_track_retained"] is True
        assert draft.audio_observations
        assert draft.audio_observations[0]["evidence_refs"][0].endswith("#audio-1")
    await engine.dispose()


@pytest.mark.asyncio
async def test_model_failure_marks_job_failed_without_pseudo_draft(tmp_path) -> None:
    Session, engine = await _session(tmp_path)
    try:
        async with Session() as session:
            service = ChildMultimodalObservationService()
            service.settings.llm_api_key = ""
            service.settings.multimodal_allow_deterministic_fallback = False
            asset = await service.create_media_asset(
                session,
                filename="play.png",
                content_type="image/png",
                data=b"image bytes",
                actor="admin",
            )
            job, _draft = await service.create_analysis_job(
                session,
                payload=ChildObservationAnalysisJobCreate(
                    asset_ids=[asset.id],
                    structured_setup={"child_display_name": "小雨", "age_months": 48},
                    include_audio=True,
                ),
                actor="admin",
            )

            draft = await service.process_analysis_job(session, job_id=job.id, actor="admin")
            persisted_draft = (
                await session.execute(
                    select(ChildMultimodalObservationDraft).where(ChildMultimodalObservationDraft.analysis_job_id == job.id)
                )
            ).scalar_one_or_none()

            assert draft is None
            assert persisted_draft is None
            assert job.status == "failed"
            assert "vision analysis requires" in (job.error_message or "")
            assert job.normalized_result["phase"] == "failed"
    finally:
        get_settings().multimodal_allow_deterministic_fallback = True
        await engine.dispose()


@pytest.mark.asyncio
async def test_review_edit_reject_and_downgrade_builds_approved_payload(tmp_path) -> None:
    Session, engine = await _session(tmp_path)
    async with Session() as session:
        service = ChildMultimodalObservationService()
        asset = await service.create_media_asset(
            session,
            filename="play.png",
            content_type="image/png",
            data=b"image bytes",
            actor="admin",
        )
        job, draft = await service.create_analysis_job(
            session,
            payload=ChildObservationAnalysisJobCreate(
                asset_ids=[asset.id],
                structured_setup={"child_display_name": "小雨", "age_months": 48},
                include_audio=True,
            ),
            actor="admin",
        )
        draft = await service.process_analysis_job(session, job_id=job.id, actor="admin")
        assert draft is not None
        result = await service.review_draft(
            session,
            draft=draft,
            payload=ObservationReviewRequest(
                target_child_confirmation={"confirmed": True},
                decisions=[
                    ObservationReviewItem(
                        item_path="visible_observations[0]",
                        decision="edited",
                        final_value={"content": "孩子在日常场景中参与互动。", "confidence": 0.7, "evidence_refs": ["asset:x#frame-1"]},
                    ),
                    ObservationReviewItem(item_path="interests[0]", decision="rejected"),
                    ObservationReviewItem(item_path="temperament_hypotheses[0]", decision="downgraded"),
                ],
            ),
            actor="admin",
        )
        assert draft.status == "approved"
        assert "孩子在日常场景中参与互动" in result["approved_payload"]["natural_language_prompt"]
        assert "interests[0]" not in {item["item_path"] for item in result["approved_payload"]["approved_items"]}
        assert draft.raw_media_deleted_at is not None
        assert draft.unknowns
    await engine.dispose()


@pytest.mark.asyncio
async def test_low_target_confidence_limits_target_specific_outputs(tmp_path, monkeypatch) -> None:
    Session, engine = await _session(tmp_path)

    async def low_confidence_analyze(self, **_kwargs):
        return (
            {
                "observable_summary": "多人场景。",
                "target_child": {"description": "无法区分的儿童", "confidence": 0.2, "evidence_refs": ["asset:a#frame-1"]},
                "visible_observations": [{"content": "多人在同一场景互动。", "confidence": 0.6, "evidence_refs": ["asset:a#frame-1"]}],
                "behavior_signals": [{"content": "互动方向不明确。", "confidence": 0.5, "evidence_refs": ["asset:a#frame-1"]}],
                "temperament_hypotheses": [{"content": "目标儿童可能外向。", "confidence": 0.6, "evidence_refs": ["asset:a#frame-1"]}],
                "interests": [{"content": "可能喜欢跑动。", "confidence": 0.6, "evidence_refs": ["asset:a#frame-1"]}],
                "development_hints": {"social_cooperation": [{"content": "合作线索。", "confidence": 0.6, "evidence_refs": ["asset:a#frame-1"]}]},
                "initial_memory_candidates": [{"content": "一次互动记忆。", "confidence": 0.6, "evidence_refs": ["asset:a#frame-1"]}],
            },
            "{}",
        )

    monkeypatch.setattr("app.services.vision_model.VisionModelAdapter.analyze", low_confidence_analyze)
    async with Session() as session:
        service = ChildMultimodalObservationService()
        asset = await service.create_media_asset(
            session,
            filename="group.png",
            content_type="image/png",
            data=b"group image",
            actor="admin",
        )
        job, draft = await service.create_analysis_job(
            session,
            payload=ChildObservationAnalysisJobCreate(
                asset_ids=[asset.id],
                structured_setup={"child_display_name": "小雨", "age_months": 48},
                include_audio=True,
            ),
            actor="admin",
        )
        draft = await service.process_analysis_job(session, job_id=job.id, actor="admin")
        assert draft is not None
        assert draft.target_child["confidence_band"] == "low"
        assert draft.visible_observations
        assert draft.temperament_hypotheses == []
        assert draft.interests == []
        assert draft.development_hints == {}
        assert draft.initial_memory_candidates == []
    await engine.dispose()


@pytest.mark.asyncio
async def test_frame_batches_split_twenty_five_frames_into_three_vlm_calls(tmp_path) -> None:
    Session, engine = await _session(tmp_path)
    async with Session() as session:
        service = ChildMultimodalObservationService()
        service.settings.multimodal_frame_batch_size = 12
        asset = await service.create_media_asset(
            session,
            filename="clip.mp4",
            content_type="video/mp4",
            data=b"video bytes",
            actor="admin",
        )

        def fake_preprocess(**_kwargs):
            return {
                "status": "ready",
                "preview_refs": [
                    {
                        "ref": f"asset:{asset.id}#t={index}s",
                        "kind": "key_frame",
                        "timestamp_seconds": index,
                        "path": str(tmp_path / f"frame-{index}.jpg"),
                    }
                    for index in range(25)
                ],
                "metadata": {"audio_refs": [], "frame_refs_generated": 25},
            }

        batch_sizes: list[int] = []

        async def fake_analyze(**kwargs):
            frame_count = sum(len(item.preview_refs or []) for item in kwargs["assets"])
            batch_sizes.append(frame_count)
            return (
                {
                    "observable_summary": "批次观察",
                    "target_child": {"description": "目标儿童", "confidence": 0.9, "evidence_refs": ["asset:a#t=0s"]},
                    "visible_observations": [{"content": f"批次包含 {frame_count} 帧", "confidence": 0.6, "evidence_refs": ["asset:a#t=0s"]}],
                },
                "{}",
            )

        service.preprocessor.preprocess = fake_preprocess
        service.vision.analyze = fake_analyze
        job, _draft = await service.create_analysis_job(
            session,
            payload=ChildObservationAnalysisJobCreate(
                asset_ids=[asset.id],
                structured_setup={"child_display_name": "小雨", "age_months": 48},
                include_audio=False,
            ),
            actor="admin",
        )
        draft = await service.process_analysis_job(session, job_id=job.id, actor="admin")

        assert draft is not None
        assert batch_sizes == [12, 12, 1]
        frame_progress = job.normalized_result["frame_progress"]
        assert {key: frame_progress[key] for key in ("total", "analyzed", "failed", "pending")} == {
            "total": 25,
            "analyzed": 25,
            "failed": 0,
            "pending": 0,
        }
        assert frame_progress["total_batches"] == 3
        assert job.normalized_result["asset_progress"][asset.id]["frame_analyzed"] == 25
    await engine.dispose()
