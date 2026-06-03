import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.router import api_router
from app.core.security import hash_password
from app.db.base import Base
from app.db.session import get_session
from app.models.entities import AdminUser, RegularUser


@pytest.mark.asyncio
async def test_regular_user_can_login_and_use_observer_routes(tmp_path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'auth_roles.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with Session() as session:
        session.add(AdminUser(username="admin", password_hash=hash_password("admin-pass")))
        session.add(RegularUser(username="user", password_hash=hash_password("user-pass")))
        await session.commit()

    async def override_session():
        async with Session() as session:
            yield session

    app = FastAPI()
    app.include_router(api_router, prefix="/api")
    app.dependency_overrides[get_session] = override_session

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        login = await client.post("/api/auth/login", json={"username": "user", "password": "user-pass"})
        assert login.status_code == 200
        token = login.json()["access_token"]

        me = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert me.status_code == 200
        assert me.json() == {"username": "user", "role": "user"}

        worlds = await client.get("/api/worlds", headers={"Authorization": f"Bearer {token}"})
        assert worlds.status_code == 200

        personas = await client.get("/api/personas", headers={"Authorization": f"Bearer {token}"})
        assert personas.status_code == 401

    await engine.dispose()


@pytest.mark.asyncio
async def test_admin_login_keeps_management_access(tmp_path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'admin_auth.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with Session() as session:
        session.add(AdminUser(username="admin", password_hash=hash_password("admin-pass")))
        session.add(RegularUser(username="user", password_hash=hash_password("user-pass")))
        await session.commit()

    async def override_session():
        async with Session() as session:
            yield session

    app = FastAPI()
    app.include_router(api_router, prefix="/api")
    app.dependency_overrides[get_session] = override_session

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        login = await client.post("/api/auth/login", json={"username": "admin", "password": "admin-pass"})
        assert login.status_code == 200
        token = login.json()["access_token"]

        me = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert me.status_code == 200
        assert me.json() == {"username": "admin", "role": "admin"}

        personas = await client.get("/api/personas", headers={"Authorization": f"Bearer {token}"})
        assert personas.status_code == 200

    await engine.dispose()
