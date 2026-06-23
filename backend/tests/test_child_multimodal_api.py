import asyncio
import base64
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.deps import AuthenticatedUser, get_current_admin, get_current_user
from app.api.router import api_router
from app.api.routes.child_observations import _database_url_for_session, _should_reschedule_job
from app.core.config import get_settings
from app.db.base import Base
from app.db.session import get_session
from app.models.entities import (
    AdminUser,
    ChildMultimodalObservationDraft,
    ChildWorldDraft,
    MediaAnalysisJob,
    MediaAsset,
    SimulationWorld,
)

VALID_PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
)


async def _client(tmp_path):
    settings = get_settings()
    settings.llm_api_key = ""
    settings.multimodal_api_key = ""
    settings.multimodal_base_url = ""
    settings.multimodal_allow_deterministic_fallback = True
    settings.multimodal_media_dir = tmp_path / "media"
    settings.multimodal_preview_dir = tmp_path / "media" / "previews"
    settings.multimodal_max_upload_bytes = 256 * 1024 * 1024
    settings.multimodal_job_batch_size = 1
    settings.multimodal_audio_analysis_enabled = True

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'child_multimodal_api.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async def override_session():
        async with Session() as session:
            yield session

    async def override_admin():
        return AdminUser(id="admin-id", username="admin", password_hash="x")

    async def override_user():
        return AuthenticatedUser(username="admin", role="admin")

    app = FastAPI()
    app.include_router(api_router, prefix="/api")
    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_current_admin] = override_admin
    app.dependency_overrides[get_current_user] = override_user
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test"), Session, engine


async def _create_converted_child_world_draft(client: httpx.AsyncClient) -> str:
    upload = await client.post(
        "/api/worlds/child-observations/media",
        files=[("files", ("play.png", b"image bytes", "image/png"))],
    )
    assert upload.status_code == 201
    asset_id = upload.json()["assets"][0]["id"]
    job = await client.post(
        "/api/worlds/child-observations/analysis-jobs",
        json={
            "asset_ids": [asset_id],
            "structured_setup": {
                "child_display_name": "小雨",
                "age_months": 48,
                "caregiver_1_label": "爸爸",
                "caregiver_2_label": "妈妈",
                "kindergarten_class": "星星班",
                "peer_count": 2,
                "natural_language_prompt": "喜欢户外活动。",
                "seed": 9,
            },
            "include_audio": True,
        },
    )
    assert job.status_code == 202
    job_payload = await _wait_for_job(client, job.json()["id"])
    draft_id = job_payload["observation_draft_id"]
    review = await client.post(
        f"/api/worlds/child-observations/drafts/{draft_id}/review",
        json={
            "target_child_confirmation": {"confirmed": True},
            "decisions": [{"item_path": "visible_observations[0]", "decision": "approved"}],
            "authorization_confirmation": {"confirmed": False},
        },
    )
    assert review.status_code == 200
    convert = await client.post(f"/api/worlds/child-observations/drafts/{draft_id}/convert", json={"start_child_world_draft": True})
    assert convert.status_code == 201
    return convert.json()["child_world_draft_id"]


@pytest.mark.asyncio
async def test_media_upload_analysis_review_conversion_does_not_create_world(tmp_path) -> None:
    client, Session, engine = await _client(tmp_path)
    async with client:
        upload = await client.post(
            "/api/worlds/child-observations/media",
            files=[
                ("files", ("play.png", VALID_PNG_BYTES, "image/png")),
                ("files", ("play.mp4", b"fake-video-with-audio-track", "video/mp4")),
            ],
        )
        assert upload.status_code == 201
        assets = upload.json()["assets"]
        assert len(assets) == 2
        assert assets[0]["status"] == "uploaded"

        job = await client.post(
            "/api/worlds/child-observations/analysis-jobs",
            json={
                "asset_ids": [asset["id"] for asset in assets],
                "structured_setup": {
                    "child_display_name": "小雨",
                    "age_months": 48,
                    "caregiver_1_label": "爸爸",
                    "caregiver_2_label": "妈妈",
                    "kindergarten_class": "星星班",
                    "peer_count": 2,
                    "natural_language_prompt": "喜欢积木和户外活动。",
                    "seed": 9,
                },
                "include_audio": True,
            },
        )
        assert job.status_code == 202
        job_payload = await _wait_for_job(client, job.json()["id"])
        assert job_payload["status"] == "partial"
        assert job_payload["frame_progress"]["total"] >= 1
        assert job_payload["asset_progress"]
        draft_id = job_payload["observation_draft_id"]
        assert draft_id

        draft = await client.get(f"/api/worlds/child-observations/drafts/{draft_id}")
        assert draft.status_code == 200
        draft_payload = draft.json()
        assert draft_payload["visible_observations"]
        assert draft_payload["child_world_draft_id"] is None

        review = await client.post(
            f"/api/worlds/child-observations/drafts/{draft_id}/review",
            json={
                "target_child_confirmation": {"confirmed": True},
                "decisions": [{"item_path": "visible_observations[0]", "decision": "approved"}],
                "authorization_confirmation": {"confirmed": False},
            },
        )
        assert review.status_code == 200
        assert review.json()["raw_media_deleted"] is True

        convert = await client.post(f"/api/worlds/child-observations/drafts/{draft_id}/convert", json={"start_child_world_draft": True})
        assert convert.status_code == 201
        child_world_draft_id = convert.json()["child_world_draft_id"]
        assert child_world_draft_id

    async with Session() as session:
        worlds = (await session.execute(select(func.count()).select_from(SimulationWorld))).scalar_one()
        child_drafts = (await session.execute(select(func.count()).select_from(ChildWorldDraft))).scalar_one()
        deleted_assets = (await session.execute(select(MediaAsset).where(MediaAsset.status == "deleted"))).scalars().all()
        assert worlds == 0
        assert child_drafts == 1
        assert len(deleted_assets) == 2
        assert all(asset.storage_path is None and asset.preview_refs == [] for asset in deleted_assets)

    await engine.dispose()


@pytest.mark.asyncio
async def test_media_analysis_accepts_final_description_before_child_draft_creation(tmp_path) -> None:
    client, Session, engine = await _client(tmp_path)
    async with client:
        upload = await client.post(
            "/api/worlds/child-observations/media",
            files=[("files", ("play.png", b"not-a-real-image-but-valid-upload", "image/png"))],
        )
        assert upload.status_code == 201
        asset = upload.json()["assets"][0]

        job = await client.post(
            "/api/worlds/child-observations/analysis-jobs",
            json={
                "asset_ids": [asset["id"]],
                "structured_setup": {
                    "child_display_name": "小雨",
                    "age_months": 48,
                    "caregiver_1_label": "爸爸",
                    "caregiver_2_label": "妈妈",
                    "kindergarten_class": "星星班",
                    "peer_count": 2,
                    "natural_language_prompt": "喜欢积木和户外活动。",
                    "seed": 9,
                },
                "include_audio": True,
            },
        )
        assert job.status_code == 202
        job_payload = await _wait_for_job(client, job.json()["id"])
        draft_id = job_payload["observation_draft_id"]

        draft = await client.get(f"/api/worlds/child-observations/drafts/{draft_id}")
        assert draft.status_code == 200
        generated_description = draft.json()["generated_child_description"]
        assert generated_description

        accept = await client.post(
            f"/api/worlds/child-observations/drafts/{draft_id}/accept-description",
            json={"description": generated_description},
        )
        assert accept.status_code == 200
        assert accept.json()["raw_media_deleted"] is True
        assert accept.json()["accepted_child_description"] == generated_description

        child_draft = await client.post(
            "/api/worlds/child-drafts",
            json={
                "template_key": "curious_outgoing",
                "child_name": "小雨",
                "age_months": 48,
                "caregiver_1_label": "爸爸",
                "caregiver_2_label": "妈妈",
                "kindergarten_class": "星星班",
                "peer_count": 2,
                "natural_language_prompt": generated_description,
                "seed": 9,
                "source_observation_draft_id": draft_id,
            },
        )
        assert child_draft.status_code == 200
        child_world_draft_id = child_draft.json()["id"]

        worlds_before = await client.get("/api/worlds")
        assert worlds_before.status_code == 200
        assert worlds_before.json() == []

        confirm = await client.post(f"/api/worlds/child-drafts/{child_world_draft_id}/confirm", json={"start_running": False})
        assert confirm.status_code == 200
        assert confirm.json()["settings"]["world_type"] == "child_growth_v1"

    async with Session() as session:
        observation = await session.get(ChildMultimodalObservationDraft, draft_id)
        assert observation is not None
        assert observation.accepted_child_description == generated_description
        assert observation.child_world_draft_id == child_world_draft_id
        deleted_assets = (await session.execute(select(MediaAsset).where(MediaAsset.status == "deleted"))).scalars().all()
        assert len(deleted_assets) == 1
        assert deleted_assets[0].storage_path is None

    await engine.dispose()


@pytest.mark.asyncio
async def test_delete_observation_history_removes_unsubmitted_draft_and_media(tmp_path) -> None:
    client, Session, engine = await _client(tmp_path)
    async with client:
        upload = await client.post(
            "/api/worlds/child-observations/media",
            files=[("files", ("play.png", b"not-a-real-image-but-valid-upload", "image/png"))],
        )
        assert upload.status_code == 201
        asset_id = upload.json()["assets"][0]["id"]
        job = await client.post(
            "/api/worlds/child-observations/analysis-jobs",
            json={
                "asset_ids": [asset_id],
                "structured_setup": {
                    "child_display_name": "小雨",
                    "age_months": 48,
                    "caregiver_1_label": "爸爸",
                    "caregiver_2_label": "妈妈",
                    "kindergarten_class": "星星班",
                    "peer_count": 2,
                    "natural_language_prompt": "喜欢积木和户外活动。",
                    "seed": 9,
                },
                "include_audio": True,
            },
        )
        assert job.status_code == 202
        job_payload = await _wait_for_job(client, job.json()["id"])
        draft_id = job_payload["observation_draft_id"]
        assert draft_id

        async with Session() as session:
            session.add(ChildMultimodalObservationDraft(analysis_job_id=job_payload["id"], observable_summary="duplicate draft"))
            await session.commit()

        deleted = await client.delete(f"/api/worlds/child-observations/analysis-jobs/{job_payload['id']}")
        assert deleted.status_code == 200
        assert deleted.json()["id"] == job_payload["id"]
        assert deleted.json()["observation_draft_id"]
        assert deleted.json()["raw_media_deleted"] is True
        assert deleted.json()["deleted_asset_ids"] == [asset_id]

        missing_job = await client.get(f"/api/worlds/child-observations/analysis-jobs/{job_payload['id']}")
        assert missing_job.status_code == 404
        missing_draft = await client.get(f"/api/worlds/child-observations/drafts/{draft_id}")
        assert missing_draft.status_code == 404

    async with Session() as session:
        job_count = (await session.execute(select(func.count()).select_from(MediaAnalysisJob))).scalar_one()
        draft_count = (await session.execute(select(func.count()).select_from(ChildMultimodalObservationDraft))).scalar_one()
        asset = await session.get(MediaAsset, asset_id)
        assert job_count == 0
        assert draft_count == 0
        assert asset is not None
        assert asset.status == "deleted"
        assert asset.storage_path is None
        assert asset.preview_refs == []

    await engine.dispose()


@pytest.mark.asyncio
async def test_delete_observation_history_rejects_submitted_draft(tmp_path) -> None:
    client, Session, engine = await _client(tmp_path)
    async with client:
        upload = await client.post(
            "/api/worlds/child-observations/media",
            files=[("files", ("play.png", b"not-a-real-image-but-valid-upload", "image/png"))],
        )
        assert upload.status_code == 201
        asset_id = upload.json()["assets"][0]["id"]
        job = await client.post(
            "/api/worlds/child-observations/analysis-jobs",
            json={
                "asset_ids": [asset_id],
                "structured_setup": {
                    "child_display_name": "小雨",
                    "age_months": 48,
                    "caregiver_1_label": "爸爸",
                    "caregiver_2_label": "妈妈",
                    "kindergarten_class": "星星班",
                    "peer_count": 2,
                    "natural_language_prompt": "喜欢积木和户外活动。",
                    "seed": 9,
                },
                "include_audio": True,
            },
        )
        assert job.status_code == 202
        job_payload = await _wait_for_job(client, job.json()["id"])
        draft_id = job_payload["observation_draft_id"]
        draft = await client.get(f"/api/worlds/child-observations/drafts/{draft_id}")
        generated_description = draft.json()["generated_child_description"]
        accept = await client.post(
            f"/api/worlds/child-observations/drafts/{draft_id}/accept-description",
            json={"description": generated_description},
        )
        assert accept.status_code == 200

        deleted = await client.delete(f"/api/worlds/child-observations/analysis-jobs/{job_payload['id']}")
        assert deleted.status_code == 400
        assert "submitted observation drafts cannot be deleted" in deleted.text

    async with Session() as session:
        remaining_job = await session.get(MediaAnalysisJob, job_payload["id"])
        remaining_draft = await session.get(ChildMultimodalObservationDraft, draft_id)
        assert remaining_job is not None
        assert remaining_draft is not None

    await engine.dispose()


@pytest.mark.asyncio
async def test_converted_child_world_draft_still_requires_final_confirmation(tmp_path) -> None:
    client, _Session, engine = await _client(tmp_path)
    async with client:
        child_world_draft_id = await _create_converted_child_world_draft(client)
        worlds_before = await client.get("/api/worlds")
        assert worlds_before.status_code == 200
        assert worlds_before.json() == []

        confirm = await client.post(f"/api/worlds/child-drafts/{child_world_draft_id}/confirm", json={"start_running": False})
        assert confirm.status_code == 200
        world = confirm.json()
        assert world["settings"]["world_type"] == "child_growth_v1"

        worlds_after = await client.get("/api/worlds")
        assert len(worlds_after.json()) == 1
    await engine.dispose()


@pytest.mark.asyncio
async def test_media_upload_rejects_unsupported_and_empty_files(tmp_path) -> None:
    client, _Session, engine = await _client(tmp_path)
    async with client:
        unsupported = await client.post(
            "/api/worlds/child-observations/media",
            files=[("files", ("notes.txt", b"hello", "text/plain"))],
        )
        assert unsupported.status_code == 400

        empty = await client.post(
            "/api/worlds/child-observations/media",
            files=[("files", ("empty.png", b"", "image/png"))],
        )
        assert empty.status_code == 400
    await engine.dispose()


@pytest.mark.asyncio
async def test_media_upload_rejects_oversized_file_and_removes_partial_file(tmp_path) -> None:
    client, _Session, engine = await _client(tmp_path)
    settings = get_settings()
    settings.multimodal_max_upload_bytes = 5
    try:
        async with client:
            response = await client.post(
                "/api/worlds/child-observations/media",
                files=[("files", ("large.mp4", b"123456", "video/mp4"))],
            )
            assert response.status_code == 413
            assert "maximum upload size" in response.text
            assert list((tmp_path / "media").glob("*.mp4")) == []
    finally:
        settings.multimodal_max_upload_bytes = 256 * 1024 * 1024
        await engine.dispose()


@pytest.mark.asyncio
async def test_media_upload_keeps_successes_when_some_files_are_oversized(tmp_path) -> None:
    client, _Session, engine = await _client(tmp_path)
    settings = get_settings()
    settings.multimodal_max_upload_bytes = 5
    try:
        async with client:
            response = await client.post(
                "/api/worlds/child-observations/media",
                files=[
                    ("files", ("small.png", b"12345", "image/png")),
                    ("files", ("large.mp4", b"123456", "video/mp4")),
                ],
            )
            assert response.status_code == 201
            payload = response.json()
            assert len(payload["assets"]) == 1
            assert payload["assets"][0]["original_filename"] == "small.png"
            assert payload["assets"][0]["size_bytes"] == 5
            assert payload["errors"][0]["code"] == "upload_too_large"
            assert payload["errors"][0]["filename"] == "large.mp4"
            assert list((tmp_path / "media").glob("*.mp4")) == []
    finally:
        settings.multimodal_max_upload_bytes = 256 * 1024 * 1024
        await engine.dispose()


@pytest.mark.asyncio
async def test_video_upload_does_not_preprocess_in_upload_request(tmp_path, monkeypatch) -> None:
    def fail_preprocess(*_args, **_kwargs):
        raise AssertionError("upload must not run media preprocessing")

    monkeypatch.setattr("app.services.media_preprocessor.MediaPreprocessor.preprocess", fail_preprocess)
    client, _Session, engine = await _client(tmp_path)
    async with client:
        upload = await client.post(
            "/api/worlds/child-observations/media",
            files=[("files", ("clip.mp4", b"video bytes", "video/mp4"))],
        )
        assert upload.status_code == 201
        asset = upload.json()["assets"][0]
        assert asset["status"] == "uploaded"
        assert asset["size_bytes"] == len(b"video bytes")
        assert asset["preview_refs"] == []
    await engine.dispose()


@pytest.mark.asyncio
async def test_analysis_jobs_list_filters_and_orders_recent_jobs(tmp_path) -> None:
    client, Session, engine = await _client(tmp_path)
    base_time = datetime(2026, 6, 18, 9, 0, tzinfo=UTC)
    jobs: list[MediaAnalysisJob] = []
    statuses = ["queued", "running", "completed", "failed"]
    async with Session() as session:
        for index, status in enumerate(statuses):
            job = MediaAnalysisJob(
                status=status,
                asset_ids=[f"asset-{index}"],
                analyzed_asset_ids=[],
                pending_asset_ids=[f"asset-{index}"] if status in {"queued", "running"} else [],
                skipped_asset_ids=[],
                excluded_asset_ids=[],
                target_child={"display_name": "test-child"},
                model_provider="test",
                model_name="test-model",
                prompt_version="test-v1",
                raw_response="",
                normalized_result={
                    "phase": "aggregating" if status == "running" else status,
                    "asset_progress": {
                        f"asset-{index}": {
                            "asset_id": f"asset-{index}",
                            "filename": f"clip-{index}.mp4",
                            "status": status,
                            "frame_total": 10 + index,
                            "frame_analyzed": index,
                            "asr_status": "completed",
                            "contribution_batches": [index + 1],
                        }
                    },
                    "frame_progress": {"total": 10 + index, "analyzed": index, "failed": 0, "pending": 10},
                },
                error_message="stale timeout" if status == "completed" else "",
                created_at=base_time + timedelta(minutes=index),
                updated_at=base_time + timedelta(minutes=index, seconds=30),
            )
            session.add(job)
            jobs.append(job)
        await session.flush()
        older_draft = ChildMultimodalObservationDraft(
            analysis_job_id=jobs[2].id,
            observable_summary="older",
            created_at=base_time + timedelta(minutes=2),
            updated_at=base_time + timedelta(minutes=2),
        )
        newer_draft = ChildMultimodalObservationDraft(
            analysis_job_id=jobs[2].id,
            observable_summary="newer",
            created_at=base_time + timedelta(minutes=3),
            updated_at=base_time + timedelta(minutes=3),
        )
        session.add_all([older_draft, newer_draft])
        await session.commit()

    async with client:
        all_response = await client.get("/api/worlds/child-observations/analysis-jobs?status=all&limit=3")
        assert all_response.status_code == 200
        all_payload = all_response.json()
        assert [row["status"] for row in all_payload] == ["failed", "completed", "running"]
        assert all_payload[1]["observation_draft_id"] == newer_draft.id
        assert all_payload[1]["error_message"] == ""
        assert all_payload[0]["frame_progress"]["total"] == 13
        assert all_payload[0]["asset_progress"]["asset-3"]["asr_status"] == "completed"

        active_response = await client.get("/api/worlds/child-observations/analysis-jobs?status=active")
        assert active_response.status_code == 200
        assert {row["status"] for row in active_response.json()} == {"queued", "running"}

        terminal_response = await client.get("/api/worlds/child-observations/analysis-jobs?status=terminal")
        assert terminal_response.status_code == 200
        assert {row["status"] for row in terminal_response.json()} == {"completed", "failed"}

    await engine.dispose()


def test_running_job_is_not_rescheduled_inside_model_timeout_window() -> None:
    settings = get_settings()
    previous_timeout = settings.multimodal_request_timeout_seconds
    settings.multimodal_request_timeout_seconds = 240.0
    try:
        now = datetime.now(UTC)
        job = MediaAnalysisJob(
            status="running",
            asset_ids=["asset-1"],
            analyzed_asset_ids=[],
            pending_asset_ids=["asset-1"],
            skipped_asset_ids=[],
            excluded_asset_ids=[],
            target_child={},
            model_provider="moonshot",
            model_name="kimi-k2.6",
            prompt_version="test",
            raw_response="",
            normalized_result={"phase": "analyzing_frames"},
            updated_at=now - timedelta(seconds=180),
        )

        assert _should_reschedule_job(job) == (False, False)

        job.updated_at = now - timedelta(seconds=400)
        assert _should_reschedule_job(job) == (True, False)
    finally:
        settings.multimodal_request_timeout_seconds = previous_timeout


async def _wait_for_job(client: httpx.AsyncClient, job_id: str) -> dict:
    for _ in range(160):
        response = await client.get(f"/api/worlds/child-observations/analysis-jobs/{job_id}")
        assert response.status_code == 200
        payload = response.json()
        if payload["status"] in {"completed", "partial", "failed"}:
            return payload
        await asyncio.sleep(0.05)
    raise AssertionError("analysis job did not finish")


@pytest.mark.asyncio
async def test_database_url_for_session_preserves_password_for_background_jobs() -> None:
    engine = create_async_engine("postgresql+asyncpg://memory_os:memory_os@postgres:5432/memory_os")
    try:
        async with AsyncSession(bind=engine) as session:
            assert _database_url_for_session(session) == "postgresql+asyncpg://memory_os:memory_os@postgres:5432/memory_os"
    finally:
        await engine.dispose()
