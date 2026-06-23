from __future__ import annotations

import asyncio
import logging
import threading
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.deps import AuthenticatedUser, get_current_user
from app.core.config import get_settings
from app.db.session import get_session
from app.models.entities import MediaAnalysisJob, MediaAsset
from app.schemas.api import (
    ChildObservationAnalysisJobCreate,
    MediaAnalysisJobResponse,
    MediaAssetResponse,
    MediaDeleteResponse,
    MediaUploadResponse,
    ObservationConvertRequest,
    ObservationConvertResponse,
    ObservationDescriptionAcceptRequest,
    ObservationDescriptionAcceptResponse,
    ObservationDraftResponse,
    ObservationHistoryDeleteResponse,
    ObservationRejectRequest,
    ObservationRejectResponse,
    ObservationReviewRequest,
    ObservationReviewResponse,
)
from app.services.media_storage import UploadTooLargeError
from app.simulation.multimodal_observation import ChildMultimodalObservationService

logger = logging.getLogger(__name__)
_RUNNING_ANALYSIS_TASKS: dict[str, threading.Thread] = {}
_RUNNING_ANALYSIS_STARTED_AT: dict[str, datetime] = {}
_ACTIVE_ANALYSIS_STATUSES = {"queued", "running"}
_TERMINAL_ANALYSIS_STATUSES = {"completed", "partial", "failed", "cancelled"}
router = APIRouter(prefix="/worlds/child-observations", tags=["child-observations"], dependencies=[Depends(get_current_user)])


@router.post("/media", response_model=MediaUploadResponse, status_code=201)
async def upload_media(
    files: list[UploadFile] = File(...),
    draft_session_id: str | None = Form(default=None),
    session: AsyncSession = Depends(get_session),
    admin: AuthenticatedUser = Depends(get_current_user),
) -> MediaUploadResponse:
    if not files:
        raise HTTPException(status_code=400, detail="at least one media file is required")
    service = ChildMultimodalObservationService()
    assets: list[MediaAsset] = []
    errors: list[dict] = []
    for index, file in enumerate(files):
        try:
            asset = await service.create_media_asset_from_upload(
                session,
                filename=file.filename or "upload",
                content_type=file.content_type or "application/octet-stream",
                upload=file,
                actor=admin.username,
            )
            if draft_session_id:
                asset.metadata_ = {**(asset.metadata_ or {}), "draft_session_id": draft_session_id}
            assets.append(asset)
        except UploadTooLargeError as exc:
            errors.append(
                {
                    "index": index,
                    "filename": file.filename or "upload",
                    "error": str(exc),
                    "code": "upload_too_large",
                    "max_bytes": exc.max_bytes,
                }
            )
        except ValueError as exc:
            errors.append({"index": index, "filename": file.filename or "upload", "error": str(exc)})
        except Exception as exc:
            errors.append({"index": index, "filename": file.filename or "upload", "error": f"upload failed: {type(exc).__name__}"})
    if not assets:
        await session.rollback()
        detail = errors[0]["error"] if errors else "at least one media file is required"
        status_code = 413 if errors and all(error.get("code") == "upload_too_large" for error in errors) else 400
        raise HTTPException(status_code=status_code, detail=detail)
    await session.commit()
    for asset in assets:
        await session.refresh(asset)
    return MediaUploadResponse(assets=[MediaAssetResponse.model_validate(asset) for asset in assets], errors=errors)


@router.post("/analysis-jobs", response_model=MediaAnalysisJobResponse, status_code=202)
async def create_analysis_job(
    payload: ChildObservationAnalysisJobCreate,
    session: AsyncSession = Depends(get_session),
    admin: AuthenticatedUser = Depends(get_current_user),
) -> MediaAnalysisJobResponse:
    service = ChildMultimodalObservationService()
    try:
        job, draft = await service.create_analysis_job(session, payload=payload, actor=admin.username)
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await session.commit()
    await session.refresh(job)
    _schedule_analysis_job(job.id, admin.username, _database_url_for_session(session))
    return _job_response(service, job, draft.id if draft else None)


@router.get("/analysis-jobs", response_model=list[MediaAnalysisJobResponse])
async def list_analysis_jobs(
    status: str = "all",
    limit: int = 20,
    session: AsyncSession = Depends(get_session),
) -> list[MediaAnalysisJobResponse]:
    if status not in {"all", "active", "terminal"}:
        raise HTTPException(status_code=400, detail="status must be one of: all, active, terminal")
    bounded_limit = max(1, min(limit, 50))
    stmt = select(MediaAnalysisJob).order_by(MediaAnalysisJob.created_at.desc()).limit(bounded_limit)
    if status == "active":
        stmt = stmt.where(MediaAnalysisJob.status.in_(_ACTIVE_ANALYSIS_STATUSES))
    elif status == "terminal":
        stmt = stmt.where(MediaAnalysisJob.status.in_(_TERMINAL_ANALYSIS_STATUSES))
    jobs = (await session.execute(stmt)).scalars().all()
    service = ChildMultimodalObservationService()
    responses: list[MediaAnalysisJobResponse] = []
    for job in jobs:
        draft_id = await service.get_job_draft_id(session, job.id)
        responses.append(_job_response(service, job, draft_id))
    return responses


@router.get("/analysis-jobs/{job_id}", response_model=MediaAnalysisJobResponse)
async def get_analysis_job(
    job_id: str,
    session: AsyncSession = Depends(get_session),
    admin: AuthenticatedUser = Depends(get_current_user),
) -> MediaAnalysisJobResponse:
    job = await session.get(MediaAnalysisJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="analysis job not found")
    service = ChildMultimodalObservationService()
    should_schedule, force = _should_reschedule_job(job)
    if should_schedule:
        _schedule_analysis_job(job.id, admin.username, _database_url_for_session(session), force=force)
    draft_id = await service.get_job_draft_id(session, job_id)
    return _job_response(service, job, draft_id)


@router.delete("/analysis-jobs/{job_id}", response_model=ObservationHistoryDeleteResponse)
async def delete_analysis_job_history(
    job_id: str,
    session: AsyncSession = Depends(get_session),
    admin: AuthenticatedUser = Depends(get_current_user),
) -> ObservationHistoryDeleteResponse:
    job = await session.get(MediaAnalysisJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="analysis job not found")
    service = ChildMultimodalObservationService()
    try:
        result = await service.delete_analysis_history(session, job=job, actor=admin.username)
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await session.commit()
    return ObservationHistoryDeleteResponse(**result)


@router.get("/drafts/{draft_id}", response_model=ObservationDraftResponse)
async def get_observation_draft(draft_id: str, session: AsyncSession = Depends(get_session)) -> ObservationDraftResponse:
    service = ChildMultimodalObservationService()
    try:
        draft = await service.get_draft(session, draft_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    response = ObservationDraftResponse.model_validate(draft)
    response.generated_child_description = service.generated_child_description_for_draft(draft)
    job = await session.get(MediaAnalysisJob, draft.analysis_job_id)
    response.asset_states = service.asset_states(job) if job else None
    response.preview_refs = await service.get_draft_preview_refs(session, draft)
    return response


@router.post("/drafts/{draft_id}/review", response_model=ObservationReviewResponse)
async def review_observation_draft(
    draft_id: str,
    payload: ObservationReviewRequest,
    session: AsyncSession = Depends(get_session),
    admin: AuthenticatedUser = Depends(get_current_user),
) -> ObservationReviewResponse:
    service = ChildMultimodalObservationService()
    try:
        draft = await service.get_draft(session, draft_id)
        result = await service.review_draft(session, draft=draft, payload=payload, actor=admin.username)
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await session.commit()
    await session.refresh(draft)
    return ObservationReviewResponse(
        id=draft.id,
        status=draft.status,
        approved_payload=result["approved_payload"],
        raw_media_deleted=bool(result["raw_media_deleted"]),
    )


@router.post("/drafts/{draft_id}/accept-description", response_model=ObservationDescriptionAcceptResponse)
async def accept_observation_description(
    draft_id: str,
    payload: ObservationDescriptionAcceptRequest,
    session: AsyncSession = Depends(get_session),
    admin: AuthenticatedUser = Depends(get_current_user),
) -> ObservationDescriptionAcceptResponse:
    service = ChildMultimodalObservationService()
    try:
        draft = await service.get_draft(session, draft_id)
        result = await service.accept_child_description(session, draft=draft, payload=payload, actor=admin.username)
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await session.commit()
    await session.refresh(draft)
    return ObservationDescriptionAcceptResponse(
        id=draft.id,
        status=draft.status,
        accepted_child_description=draft.accepted_child_description,
        raw_media_deleted=bool(result["raw_media_deleted"]),
        risk_flags=list(result["risk_flags"] or []),
    )


@router.post("/drafts/{draft_id}/convert", response_model=ObservationConvertResponse, status_code=201)
async def convert_observation_draft(
    draft_id: str,
    payload: ObservationConvertRequest,
    session: AsyncSession = Depends(get_session),
    admin: AuthenticatedUser = Depends(get_current_user),
) -> ObservationConvertResponse:
    service = ChildMultimodalObservationService()
    try:
        draft = await service.get_draft(session, draft_id)
        if not payload.start_child_world_draft:
            raise ValueError("conversion request did not start child world draft")
        child_world_draft = await service.convert_to_child_world_draft(session, draft=draft, actor=admin.username)
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await session.commit()
    await session.refresh(draft)
    return ObservationConvertResponse(
        observation_draft_id=draft.id,
        child_world_draft_id=child_world_draft.id,
        raw_media_deleted=draft.raw_media_deleted_at is not None,
    )


@router.post("/drafts/{draft_id}/reject", response_model=ObservationRejectResponse)
async def reject_observation_draft(
    draft_id: str,
    payload: ObservationRejectRequest,
    session: AsyncSession = Depends(get_session),
    admin: AuthenticatedUser = Depends(get_current_user),
) -> ObservationRejectResponse:
    service = ChildMultimodalObservationService()
    try:
        draft = await service.get_draft(session, draft_id)
        deleted = await service.reject_draft(session, draft=draft, reason=payload.reason, actor=admin.username)
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await session.commit()
    await session.refresh(draft)
    return ObservationRejectResponse(id=draft.id, status=draft.status, raw_media_deleted=deleted)


@router.delete("/media/{asset_id}", response_model=MediaDeleteResponse)
async def delete_media_asset(
    asset_id: str,
    session: AsyncSession = Depends(get_session),
    admin: AuthenticatedUser = Depends(get_current_user),
) -> MediaDeleteResponse:
    asset = await session.get(MediaAsset, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="media asset not found")
    service = ChildMultimodalObservationService()
    asset = await service.delete_media(session, asset=asset, actor=admin.username, reason="operator_requested")
    await session.commit()
    await session.refresh(asset)
    return MediaDeleteResponse(id=asset.id, status=asset.status, deleted_at=asset.deleted_at)


def _job_response(service: ChildMultimodalObservationService, job: MediaAnalysisJob, draft_id: str | None) -> MediaAnalysisJobResponse:
    normalized = job.normalized_result or {}
    frame_progress = normalized.get("frame_progress") if isinstance(normalized.get("frame_progress"), dict) else {}
    return MediaAnalysisJobResponse(
        id=job.id,
        status=job.status,
        phase=str(normalized.get("phase") or job.status),
        asset_states=service.asset_states(job),
        asset_progress=normalized.get("asset_progress") if isinstance(normalized.get("asset_progress"), dict) else {},
        frame_progress={
            "total": int(frame_progress.get("total") or 0),
            "analyzed": int(frame_progress.get("analyzed") or 0),
            "failed": int(frame_progress.get("failed") or 0),
            "pending": int(frame_progress.get("pending") or 0),
        },
        target_child=job.target_child,
        observation_draft_id=draft_id,
        error_message="" if job.status == "completed" else job.error_message,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


async def _process_analysis_job(job_id: str, actor: str, database_url: str) -> None:
    connect_args = {"check_same_thread": False, "timeout": 30} if database_url.startswith("sqlite") else {}
    engine = create_async_engine(database_url, echo=False, future=True, connect_args=connect_args)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    service = ChildMultimodalObservationService()
    logger.info("child observation analysis job started", extra={"job_id": job_id})
    try:
        async with Session() as session:
            try:
                await service.process_analysis_job(session, job_id=job_id, actor=actor)
                await session.commit()
                logger.info("child observation analysis job finished", extra={"job_id": job_id})
            except Exception as exc:
                logger.exception("child observation analysis job crashed", extra={"job_id": job_id})
                await session.rollback()
                job = await session.get(MediaAnalysisJob, job_id)
                if job is not None:
                    normalized = job.normalized_result or {}
                    job.status = "failed"
                    job.error_message = f"background task crashed: {type(exc).__name__}"
                    job.normalized_result = {**normalized, "phase": "failed"}
                    await session.commit()
    finally:
        await engine.dispose()


def _run_analysis_job_thread(job_id: str, actor: str, database_url: str) -> None:
    asyncio.run(_process_analysis_job(job_id, actor, database_url))


def _schedule_analysis_job(job_id: str, actor: str, database_url: str, *, force: bool = False) -> None:
    existing = _RUNNING_ANALYSIS_TASKS.get(job_id)
    if existing and existing.is_alive():
        return
    if existing:
        _RUNNING_ANALYSIS_TASKS.pop(job_id, None)
        _RUNNING_ANALYSIS_STARTED_AT.pop(job_id, None)
    _RUNNING_ANALYSIS_STARTED_AT[job_id] = datetime.now(UTC)
    thread = threading.Thread(target=_run_analysis_job_thread, args=(job_id, actor, database_url), daemon=True)
    _RUNNING_ANALYSIS_TASKS[job_id] = thread
    logger.info("child observation analysis job scheduled", extra={"job_id": job_id, "force": force})
    thread.start()


def _should_reschedule_job(job: MediaAnalysisJob) -> tuple[bool, bool]:
    existing = _RUNNING_ANALYSIS_TASKS.get(job.id)
    if existing and not existing.is_alive():
        _RUNNING_ANALYSIS_TASKS.pop(job.id, None)
        _RUNNING_ANALYSIS_STARTED_AT.pop(job.id, None)
        existing = None
    if job.status == "queued":
        if existing:
            return False, False
        created_at = _as_aware_utc(job.created_at)
        return datetime.now(UTC) - created_at >= timedelta(seconds=5), False
    if job.status == "running":
        settings = get_settings()
        stale_after = max(120.0, float(settings.multimodal_request_timeout_seconds) + 90.0)
        updated_at = _as_aware_utc(job.updated_at)
        is_db_stale = datetime.now(UTC) - updated_at >= timedelta(seconds=stale_after)
        if not is_db_stale:
            return False, False
        task_started_at = _RUNNING_ANALYSIS_STARTED_AT.get(job.id)
        force_after = stale_after + 120.0
        force = bool(existing and task_started_at and datetime.now(UTC) - task_started_at >= timedelta(seconds=force_after))
        return (not existing) or force, force
    return False, False


def _database_url_for_session(session: AsyncSession) -> str:
    bind = session.bind
    url = getattr(bind, "url", None)
    if url is not None and hasattr(url, "render_as_string"):
        return url.render_as_string(hide_password=False)
    return str(url) if url is not None else get_settings().database_url


def _as_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
