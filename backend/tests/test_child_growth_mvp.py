from datetime import datetime

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.deps import AuthenticatedUser, get_current_admin, get_current_user
from app.api.router import api_router
from app.core.config import get_settings
from app.db.base import Base
from app.db.session import get_session
from app.models.entities import AdminUser, AgentRelationship, GrowthReport, MemoryRecord, SimulationWorld, WorldSnapshot
from app.simulation.child_growth import ChildGrowthStepper, default_development


@pytest.mark.asyncio
async def test_child_growth_draft_confirm_step_report_and_replay(tmp_path) -> None:
    settings = get_settings()
    settings.llm_api_key = ""
    settings.simulation_step_minutes = 720

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'child_growth.db'}")
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
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        draft_resp = await client.post(
            "/api/worlds/child-drafts",
            json={
                "template_key": "sensitive_slow_to_warm",
                "child_name": "小禾",
                "age_months": 50,
                "caregiver_1_label": "爸爸",
                "caregiver_2_label": "妈妈",
                "kindergarten_class": "星星班",
                "peer_count": 3,
                "natural_language_prompt": "喜欢积木，入园时有一点慢热。",
                "seed": 42,
            },
        )
        assert draft_resp.status_code == 200
        draft = draft_resp.json()
        assert draft["parsed_draft"]["child"]["traits"]["age_months"] == 50
        assert draft["created_world_id"] is None

        confirm_resp = await client.post(f"/api/worlds/child-drafts/{draft['id']}/confirm", json={"start_running": False})
        assert confirm_resp.status_code == 200
        world = confirm_resp.json()
        assert world["settings"]["world_type"] == "child_growth_v1"
        world_id = world["id"]

        state_resp = await client.get(f"/api/worlds/{world_id}/state")
        state = state_resp.json()
        assert state["child"]["agent"]["name"] == "小禾"
        assert {location["kind"] for location in state["locations"]} == {"home", "kindergarten", "community"}
        assert len(state["relationships"]) >= 5
        assert len([agent for agent in state["agents"] if agent["traits"].get("role") == "peer"]) >= 2
        kindergarten_location_id = next(location["id"] for location in state["locations"] if location["kind"] == "kindergarten")

        for forbidden_payload in (
            {"needs": {"energy": 100}},
            {"development": {"language_communication": {"score": 100}}},
            {"traits": {"temperament_baseline": "直接改写"}},
        ):
            bad_intervention = await client.post(
                f"/api/worlds/{world_id}/interventions",
                json={"intervention_type": "gm_event", "payload": forbidden_payload},
            )
            assert bad_intervention.status_code == 400

        good_intervention = await client.post(
            f"/api/worlds/{world_id}/interventions",
            json={
                "intervention_type": "npc_behavior",
                "payload": {
                    "text": "老师今天在入园时蹲下来提醒，引导小禾加入积木活动。",
                    "location_id": kindergarten_location_id,
                    "target_role": "teacher",
                    "activity_goal": "积木合作活动",
                    "guidance_style": "蹲下来分步骤提示",
                },
            },
        )
        assert good_intervention.status_code == 200

        first_step = await client.post(f"/api/worlds/{world_id}/step")
        assert first_step.status_code == 200
        first_event = first_step.json()["events"][0]
        assert first_step.json()["world"]["tick_no"] == 1
        assert first_event["payload"]["main_action"]
        assert first_event["payload"]["observed_facts"]
        assert first_event["payload"]["child_interpretation"]
        assert first_event["payload"]["gm_interpretation"]
        assert "Deterministic fallback" not in first_event["payload"]["gm_interpretation"]
        assert first_event["payload"]["state_update_evidence"]
        assert first_event["payload"]["half_day_summary"]
        assert first_event["location_id"] == kindergarten_location_id
        assert first_event["payload"]["main_action"] == "积木合作活动"
        assert "积木合作活动" in first_event["payload"]["action_text"]
        assert first_event["payload"]["intervention_plan"]["target_role"] == "teacher"
        assert first_event["payload"]["intervention_plan"]["activity_goal"] == "积木合作活动"
        assert first_event["payload"]["intervention_plan"]["location_id"] == kindergarten_location_id
        assert "积木合作活动" in first_event["payload"]["intervention_effect_summary"]
        first_slice = first_event["payload"]["life_slice"]
        assert first_slice["scene_description"]
        assert 10 <= len(first_slice["dialogue"]) <= 20
        slice_text = first_slice["scene_description"] + "\n" + "\n".join(f"{turn['speaker']}：{turn['text']}" for turn in first_slice["dialogue"])
        assert "老师" in slice_text or "林老师" in slice_text
        assert "积木" in slice_text
        assert "照护者" not in slice_text
        child_summaries = first_step.json()["state"]["child"]["half_day_summaries"]
        assert child_summaries[-1]["life_slice"]["dialogue"]
        first_development = first_step.json()["state"]["child"]["development"]
        assert first_development["language_communication"]["evidence_count"] > 0
        assert first_development["language_communication"]["recent_delta"] != first_development["motor_ability"]["recent_delta"]
        assert "recent_confidence" in first_development["language_communication"]
        interventions_after_first_step = await client.get(f"/api/worlds/{world_id}/interventions")
        assert interventions_after_first_step.json()[0]["status"] == "applied"
        assert interventions_after_first_step.json()[0]["result_event_id"] == first_event["id"]

        location_override = await client.post(
            f"/api/worlds/{world_id}/interventions",
            json={
                "intervention_type": "environment_event",
                "payload": {
                    "text": "上午的教室材料还需要老师带小禾补一次整理。",
                    "location_id": kindergarten_location_id,
                    "target_role": "teacher",
                    "activity_goal": "教室整理材料",
                },
            },
        )
        assert location_override.status_code == 200

        second_step = await client.post(f"/api/worlds/{world_id}/step")
        assert second_step.status_code == 200
        second_event = second_step.json()["events"][0]
        assert second_step.json()["world"]["tick_no"] == 2
        assert second_event["location_id"] == kindergarten_location_id
        assert second_event["payload"]["main_action"] == "教室整理材料"
        assert second_event["payload"]["intervention_plan"]["scene"] == "kindergarten"

        home_summaries: list[str] = []
        for _ in range(12):
            step_resp = await client.post(f"/api/worlds/{world_id}/step")
            assert step_resp.status_code == 200
            event_payload = step_resp.json()["events"][0]["payload"]
            if event_payload["main_action"] == "回家后的用餐、亲子互动和整理":
                home_summaries.append(event_payload["half_day_summary"])

        assert len(set(home_summaries[:2])) > 1

        report_resp = await client.get(f"/api/worlds/{world_id}/growth-reports")
        reports = report_resp.json()
        assert reports
        assert reports[0]["period_end_tick"] == 14
        assert "disclaimer" in reports[0]["report"]
        report_trends = reports[0]["report"]["development_trends"]
        assert "recent_delta" in report_trends["language_communication"]
        assert "recent_confidence" in report_trends["language_communication"]
        development_after_week = step_resp.json()["state"]["child"]["development"]
        confidence_values = {row["confidence"] for row in development_after_week.values()}
        assert len(confidence_values) > 1

        relationships_resp = await client.get(f"/api/worlds/{world_id}/relationships")
        assert len(relationships_resp.json()) >= 5

        snapshots_resp = await client.get(f"/api/worlds/{world_id}/snapshots")
        snapshots = snapshots_resp.json()
        assert len(snapshots) >= 14
        assert snapshots[0]["state"]["child"]["needs"]

        branch_resp = await client.post(
            f"/api/worlds/{world_id}/branches/preview",
            json={"snapshot_id": snapshots[0]["id"], "label": "测试分支占位"},
        )
        assert branch_resp.status_code == 200
        assert branch_resp.json()["available"] is False
        assert branch_resp.json()["requested_snapshot_id"] == snapshots[0]["id"]

    async with Session() as session:
        db_world = (await session.execute(select(SimulationWorld).where(SimulationWorld.id == world_id))).scalar_one()
        relationships = (await session.execute(select(AgentRelationship).where(AgentRelationship.world_id == world_id))).scalars().all()
        reports = (await session.execute(select(GrowthReport).where(GrowthReport.world_id == world_id))).scalars().all()
        snapshots = (await session.execute(select(WorldSnapshot).where(WorldSnapshot.world_id == world_id))).scalars().all()
        memories = (await session.execute(select(MemoryRecord))).scalars().all()

    await engine.dispose()

    assert db_world.tick_no == 14
    assert datetime.fromisoformat(db_world.clock_time.isoformat()) == db_world.clock_time
    assert relationships
    assert reports
    assert snapshots
    assert memories


def test_development_domains_use_independent_recent_evidence() -> None:
    stepper = ChildGrowthStepper()
    development = default_development(48)
    outcome = {
        "main_action": "music stop movement game",
        "half_day_summary": "The child joined a music stop movement game and controlled body movement.",
        "observed_facts": ["movement game", "followed stop rule"],
        "gm_interpretation": "Primary evidence is motor control, with secondary attention and peer cooperation.",
        "state_update_evidence": [],
        "suggested_updates": {
            "development_evidence": [
                {"domain": "motor_ability", "role": "primary", "impact": 0.6, "source": "test_activity"},
                {"domain": "cognitive_attention", "role": "secondary", "impact": 0.3, "source": "test_activity"},
                {"domain": "social_cooperation", "role": "secondary", "impact": 0.3, "source": "test_activity"},
            ]
        },
    }

    for tick_no in range(1, 4):
        development = stepper._updated_development(development, outcome=outcome, tick_no=tick_no)

    assert development["motor_ability"]["recent_delta"] > development["cognitive_attention"]["recent_delta"]
    assert development["cognitive_attention"]["recent_delta"] > development["self_care_habits"]["recent_delta"]
    assert development["motor_ability"]["recent_confidence"] > development["self_care_habits"]["recent_confidence"]
    assert development["motor_ability"]["confidence"] != development["self_care_habits"]["confidence"]
    assert development["motor_ability"]["score"] == default_development(48)["motor_ability"]["score"]


def test_development_domains_allow_independent_negative_evidence_and_settlement() -> None:
    stepper = ChildGrowthStepper()
    development = default_development(48)
    challenge_outcome = {
        "main_action": "peer conflict repair",
        "half_day_summary": "A peer conflict made the child upset and tired before adult support helped repair it.",
        "observed_facts": ["peer conflict", "child was tired"],
        "gm_interpretation": "Challenge evidence for social cooperation and emotional regulation.",
        "state_update_evidence": [],
        "suggested_updates": {
            "development_evidence": [
                {"domain": "social_cooperation", "role": "challenge", "impact": -0.7, "source": "test_challenge"},
                {"domain": "emotional_regulation", "role": "challenge", "impact": -0.7, "source": "test_challenge"},
            ]
        },
    }

    development = stepper._updated_development(development, outcome=challenge_outcome, tick_no=1)

    assert development["social_cooperation"]["recent_delta"] < 0
    assert development["emotional_regulation"]["recent_trend"] == "down"
    assert development["language_communication"]["recent_delta"] == 0

    motor_outcome = {
        "main_action": "outdoor run and jump movement",
        "half_day_summary": "The child repeatedly practiced outdoor run and jump movement.",
        "observed_facts": ["run and jump"],
        "gm_interpretation": "Strong repeated motor evidence.",
        "state_update_evidence": [],
        "suggested_updates": {
            "development_evidence": [
                {"domain": "motor_ability", "role": "primary", "impact": 0.8, "source": "test_motor"},
            ]
        },
    }
    motor_development = default_development(48)
    for tick_no in range(1, 15):
        motor_development = stepper._updated_development(motor_development, outcome=motor_outcome, tick_no=tick_no)
    settled = stepper._settle_development(motor_development)

    assert settled["motor_ability"]["last_settlement_delta"] == 2
    assert settled["motor_ability"]["score"] == default_development(48)["motor_ability"]["score"] + 2
    assert settled["language_communication"]["last_settlement_delta"] == 0
    assert settled["motor_ability"]["evidence_buffer"]


@pytest.mark.asyncio
async def test_child_draft_high_risk_confirm_is_rejected(tmp_path) -> None:
    settings = get_settings()
    settings.llm_api_key = ""

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'risk.db'}")
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
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        draft_resp = await client.post(
            "/api/worlds/child-drafts",
            json={"natural_language_prompt": "使用真实姓名、身份证和照片来模拟现实儿童。"},
        )
        assert draft_resp.status_code == 200
        assert draft_resp.json()["risk_flags"]

        confirm_resp = await client.post(f"/api/worlds/child-drafts/{draft_resp.json()['id']}/confirm", json={})
        assert confirm_resp.status_code == 400

    await engine.dispose()
