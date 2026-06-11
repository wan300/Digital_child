from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.router import api_router
from app.core.security import hash_password, verify_password
from app.db.base import Base
from app.db.init_db import ensure_admin_user
from app.db.session import get_session
from app.models.entities import AdminUser, Persona, RegularUser


@pytest.mark.asyncio
async def test_authorization_is_not_required_and_everyone_is_admin(tmp_path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'auth_disabled.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with Session() as session:
        session.add(Persona(name="Ada", persona_block="Ada is practical."))
        await session.commit()

    async def override_session():
        async with Session() as session:
            yield session

    app = FastAPI()
    app.include_router(api_router, prefix="/api")
    app.dependency_overrides[get_session] = override_session

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        me = await client.get("/api/auth/me")
        assert me.status_code == 200
        assert me.json() == {"username": "admin", "role": "admin"}

        login = await client.post("/api/auth/login", json={"username": "anyone", "password": "wrong"})
        assert login.status_code == 200
        assert login.json()["access_token"] == "auth-disabled"

        logout = await client.post("/api/auth/logout")
        assert logout.status_code == 200

        worlds = await client.get("/api/worlds")
        assert worlds.status_code == 200

        personas = await client.get("/api/personas")
        assert personas.status_code == 200
        assert personas.json()[0]["name"] == "Ada"

    await engine.dispose()


@pytest.mark.asyncio
async def test_legacy_env_managed_account_passwords_can_still_be_refreshed(tmp_path, monkeypatch) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'refreshed_auth.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with Session() as session:
        session.add(AdminUser(username="admin", password_hash=hash_password("old-admin-pass")))
        session.add(RegularUser(username="user", password_hash=hash_password("old-user-pass")))
        await session.commit()

    settings = SimpleNamespace(
        admin_username="admin",
        admin_password="12345678",
        user_username="user",
        user_password="12345678",
    )
    monkeypatch.setattr("app.db.init_db.get_settings", lambda: settings)

    async with Session() as session:
        await ensure_admin_user(session)

        admin = (await session.execute(select(AdminUser).where(AdminUser.username == "admin"))).scalar_one()
        user = (await session.execute(select(RegularUser).where(RegularUser.username == "user"))).scalar_one()

        assert verify_password("12345678", admin.password_hash)
        assert verify_password("12345678", user.password_hash)

    await engine.dispose()
