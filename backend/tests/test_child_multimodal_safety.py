import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.db.base import Base
from app.models.entities import ChildMultimodalObservationDraft
from app.schemas.api import (
    ChildObservationAnalysisJobCreate,
    ObservationDescriptionAcceptRequest,
    ObservationReviewRequest,
)
from app.simulation.multimodal_observation import ChildMultimodalObservationService


async def _draft(tmp_path, prompt: str):
    settings = get_settings()
    settings.llm_api_key = ""
    settings.multimodal_allow_deterministic_fallback = True
    settings.multimodal_media_dir = tmp_path / "media"
    settings.multimodal_preview_dir = tmp_path / "media" / "previews"
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'child_multimodal_safety.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    session = Session()
    service = ChildMultimodalObservationService()
    asset = await service.create_media_asset(
        session,
        filename="risk.png",
        content_type="image/png",
        data=b"risk image",
        actor="admin",
    )
    job, draft = await service.create_analysis_job(
        session,
        payload=ChildObservationAnalysisJobCreate(
            asset_ids=[asset.id],
            structured_setup={"child_display_name": "小雨", "age_months": 48, "natural_language_prompt": prompt},
            include_audio=True,
        ),
        actor="admin",
    )
    draft = await service.process_analysis_job(session, job_id=job.id, actor="admin")
    assert draft is not None
    return session, service, draft, engine


@pytest.mark.asyncio
async def test_prohibited_claims_are_hard_blocked_even_with_authorization(tmp_path) -> None:
    session, service, draft, engine = await _draft(tmp_path, "请根据人脸识别身份，并判断孩子智力。")
    try:
        assert any(flag["severity"] == "prohibited" for flag in draft.risk_flags)
        with pytest.raises(ValueError, match="prohibited"):
            await service.review_draft(
                session,
                draft=draft,
                payload=ObservationReviewRequest(
                    target_child_confirmation={"confirmed": True},
                    authorization_confirmation={
                        "confirmed": True,
                        "authorization_scope": ["all"],
                        "risk_categories": ["identity"],
                        "operator_rationale": "测试授权",
                    },
                ),
                actor="admin",
            )
    finally:
        await session.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_high_risk_requires_additional_authorization_and_records_scope(tmp_path) -> None:
    session, service, draft, engine = await _draft(tmp_path, "备注里包含身份证 110101202001011234，需要继续测试。")
    try:
        assert any(flag["severity"] == "high" for flag in draft.risk_flags)
        with pytest.raises(ValueError, match="authorization"):
            await service.review_draft(
                session,
                draft=draft,
                payload=ObservationReviewRequest(target_child_confirmation={"confirmed": True}),
                actor="admin",
            )

        result = await service.review_draft(
            session,
            draft=draft,
            payload=ObservationReviewRequest(
                target_child_confirmation={"confirmed": True},
                authorization_confirmation={
                    "confirmed": True,
                    "authorization_scope": ["validation_only"],
                    "risk_categories": ["real_identifier"],
                    "operator_rationale": "本地测试验证",
                    "retained_content_scope": "仅保留审核文字观察",
                },
            ),
            actor="admin",
        )
        assert draft.status == "approved"
        assert draft.authorization_confirmation["confirmed"] is True
        assert draft.authorization_confirmation["confirmed_by"] == "admin"
        assert result["raw_media_deleted"] is True
    finally:
        await session.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_accept_description_blocks_prohibited_draft_even_when_description_is_safe(tmp_path) -> None:
    session, service, draft, engine = await _draft(tmp_path, "请根据人脸识别身份，并判断孩子智力。")
    try:
        assert any(flag["severity"] == "prohibited" for flag in draft.risk_flags)
        with pytest.raises(ValueError, match="prohibited"):
            await service.accept_child_description(
                session,
                draft=draft,
                payload=ObservationDescriptionAcceptRequest(description="小雨是一名喜欢日常互动的儿童。"),
                actor="admin",
            )
    finally:
        await session.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_accept_description_allows_high_risk_removed_from_final_text(tmp_path) -> None:
    session, service, draft, engine = await _draft(tmp_path, "备注里包含身份证 110101202001011234，需要继续测试。")
    try:
        assert any(flag["severity"] == "high" for flag in draft.risk_flags)
        result = await service.accept_child_description(
            session,
            draft=draft,
            payload=ObservationDescriptionAcceptRequest(description="小雨是一名约48个月的儿童，对日常互动和熟悉活动有参与意愿。"),
            actor="admin",
        )
        assert draft.status == "description_accepted"
        assert draft.accepted_child_description.startswith("小雨")
        assert result["raw_media_deleted"] is True
    finally:
        await session.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_accept_description_requires_authorization_for_retained_high_risk_text(tmp_path) -> None:
    session, service, draft, engine = await _draft(tmp_path, "日常观察。")
    try:
        with pytest.raises(ValueError, match="authorization"):
            await service.accept_child_description(
                session,
                draft=draft,
                payload=ObservationDescriptionAcceptRequest(description="小雨的身份证 110101202001011234 被记录在备注中。"),
                actor="admin",
            )

        await service.accept_child_description(
            session,
            draft=draft,
            payload=ObservationDescriptionAcceptRequest(
                description="小雨的身份证 110101202001011234 被记录在备注中。",
                authorization_confirmation={
                    "confirmed": True,
                    "authorization_scope": ["validation_only"],
                    "risk_categories": ["real_identifier"],
                    "operator_rationale": "本地测试验证",
                    "retained_content_scope": "最终描述测试",
                },
            ),
            actor="admin",
        )
        assert draft.authorization_confirmation["confirmed_by"] == "admin"
    finally:
        await session.close()
        await engine.dispose()


def test_safety_disclaimer_does_not_count_as_prohibited_claim() -> None:
    service = ChildMultimodalObservationService()

    disclaimer_flags = service._risk_flags(
        "The image cannot be used for face recognition, identity matching, or appearance-based personality inference."
    )
    prohibited_flags = service._risk_flags(
        "Use face recognition to identify the child and infer appearance personality from looks."
    )

    assert not any(flag["severity"] == "prohibited" for flag in disclaimer_flags)
    assert any(flag["severity"] == "prohibited" for flag in prohibited_flags)


def test_legacy_draft_without_generated_description_gets_response_fallback() -> None:
    service = ChildMultimodalObservationService()
    draft = ChildMultimodalObservationDraft(
        structured_setup={"child_display_name": "child", "age_months": 48},
        target_child={"confidence": 0.82},
        observable_summary="media summary",
        generated_child_description="",
        visible_observations=[{"content": "visible observation", "confidence": 0.7}],
        audio_observations=[],
        behavior_signals=[{"content": "behavior signal", "confidence": 0.7}],
        temperament_hypotheses=[],
        interests=[],
        development_hints={},
        initial_memory_candidates=[],
        unknowns=[{"content": "unknown content", "confidence": 0.5}],
    )

    description = service.generated_child_description_for_draft(draft)

    assert description
    assert "child" in description
    assert "media summary" in description
    assert "unknown content" in description
    assert "{'content'" not in description


def test_generated_child_description_excludes_audio_transcript_text() -> None:
    service = ChildMultimodalObservationService()
    draft = ChildMultimodalObservationDraft(
        structured_setup={"child_display_name": "小雨", "age_months": 48},
        target_child={"confidence": 0.82},
        observable_summary="visual media summary",
        generated_child_description="",
        visible_observations=[{"content": "孩子在儿童乐园里观察并参与活动", "confidence": 0.7}],
        audio_observations=[{"content": "小小的花园里面挖呀挖呀挖", "confidence": 0.5}],
        behavior_signals=[{"content": "会走动、停留并接近可操作物件", "confidence": 0.7}],
        temperament_hypotheses=[{"content": "在成人陪伴下更愿意尝试新活动", "confidence": 0.6}],
        interests=[{"content": "对球、沙地和互动装置表现出兴趣", "confidence": 0.7}],
        development_hints={"social": [{"content": "更常见观察和并行游戏线索", "confidence": 0.6}]},
        initial_memory_candidates=[{"content": "有一次在户外参与玩沙活动的经历", "confidence": 0.6}],
        unknowns=[{"content": "无法从媒体可靠判断长期能力、家庭背景或稳定人格。", "confidence": 0.5}],
    )

    description = service.generated_child_description_for_draft(draft)

    assert "当前儿童的主要特征" in description
    assert "简要画像" in description
    assert "观察边界" in description
    assert "挖呀挖" not in description
    assert "audio_observations" not in description
    assert "{'content'" not in description
