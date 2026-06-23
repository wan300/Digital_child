from sqlalchemy import inspect, select
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import hash_password, verify_password
from app.db.base import Base
from app.db.session import engine
from app.models.entities import AdminUser, RegularUser

_SCHEMA_COMPAT_COLUMNS: dict[str, dict[str, str]] = {
    "child_multimodal_observation_drafts": {
        "generated_child_description": "TEXT NOT NULL DEFAULT ''",
        "accepted_child_description": "TEXT NOT NULL DEFAULT ''",
    },
}


async def create_db_and_tables() -> None:
    settings = get_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_ensure_schema_compatibility)


def _ensure_schema_compatibility(sync_connection: Connection) -> None:
    inspector = inspect(sync_connection)
    table_names = set(inspector.get_table_names())
    for table_name, required_columns in _SCHEMA_COMPAT_COLUMNS.items():
        if table_name not in table_names:
            continue
        existing_columns = {column["name"] for column in inspector.get_columns(table_name)}
        for column_name, column_definition in required_columns.items():
            if column_name not in existing_columns:
                sync_connection.exec_driver_sql(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_definition}")


async def ensure_admin_user(session: AsyncSession) -> None:
    settings = get_settings()
    result = await session.execute(select(AdminUser).where(AdminUser.username == settings.admin_username))
    admin = result.scalar_one_or_none()
    if admin is None:
        session.add(AdminUser(username=settings.admin_username, password_hash=hash_password(settings.admin_password)))
        await session.commit()
    elif not verify_password(settings.admin_password, admin.password_hash):
        admin.password_hash = hash_password(settings.admin_password)
        await session.commit()

    if settings.user_username and settings.user_password:
        result = await session.execute(select(RegularUser).where(RegularUser.username == settings.user_username))
        user = result.scalar_one_or_none()
        if user is None:
            session.add(RegularUser(username=settings.user_username, password_hash=hash_password(settings.user_password)))
            await session.commit()
        elif not verify_password(settings.user_password, user.password_hash):
            user.password_hash = hash_password(settings.user_password)
            await session.commit()
