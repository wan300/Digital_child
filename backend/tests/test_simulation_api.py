import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.deps import AuthenticatedUser, get_current_admin, get_current_user
from app.api.router import api_router
from app.db.base import Base
from app.db.session import get_session
from app.models.entities import AdminUser, AuditLog, Persona, UserIntervention


@pytest.mark.asyncio
async def test_simulation_api_world_lifecycle_and_step(tmp_path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'api.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with Session() as session:
        session.add(Persona(id="p1", name="Ada", persona_block="Ada is practical."))
        await session.commit()

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
        world_resp = await client.post("/api/worlds", json={"name": "API Town", "seed": 3})
        assert world_resp.status_code == 200
        world_id = world_resp.json()["id"]

        location_resp = await client.post(f"/api/worlds/{world_id}/locations", json={"name": "Square", "x": 1, "y": 2})
        assert location_resp.status_code == 200
        location_id = location_resp.json()["id"]

        agent_resp = await client.post(
            f"/api/worlds/{world_id}/agents",
            json={"persona_id": "p1", "current_location_id": location_id},
        )
        assert agent_resp.status_code == 200
        assert agent_resp.json()["state"]["mood"] == "neutral"

        rule_resp = await client.post(
            f"/api/worlds/{world_id}/rules",
            json={"title": "Civility", "content": "Residents should be civil.", "priority": 1},
        )
        assert rule_resp.status_code == 200

        intervention_resp = await client.post(
            f"/api/worlds/{world_id}/interventions",
            json={"intervention_type": "gm_event", "payload": {"text": "A visitor arrives."}},
        )
        assert intervention_resp.status_code == 200
        assert intervention_resp.json()["status"] == "pending"

        assert (await client.post(f"/api/worlds/{world_id}/start")).json()["status"] == "running"
        assert (await client.post(f"/api/worlds/{world_id}/pause")).json()["status"] == "paused"

        step_resp = await client.post(f"/api/worlds/{world_id}/step")
        assert step_resp.status_code == 200
        assert step_resp.json()["world"]["tick_no"] == 1
        assert step_resp.json()["events"]
        interventions_after_step = await client.get(f"/api/worlds/{world_id}/interventions")
        assert interventions_after_step.json()[0]["status"] == "applied"

        state_resp = await client.get(f"/api/worlds/{world_id}/state")
        assert state_resp.status_code == 200
        assert state_resp.json()["agents"][0]["name"] == "Ada"

        events_resp = await client.get(f"/api/worlds/{world_id}/events")
        assert events_resp.status_code == 200
        assert len(events_resp.json()) >= 1

        assert (await client.post(f"/api/worlds/{world_id}/resume")).json()["status"] == "running"

    async with Session() as session:
        audit_rows = (await session.execute(AuditLog.__table__.select())).all()
        intervention_rows = (await session.execute(UserIntervention.__table__.select())).all()

    await engine.dispose()

    assert audit_rows
    assert intervention_rows
