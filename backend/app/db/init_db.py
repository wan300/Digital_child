from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import hash_password, verify_password
from app.db.base import Base
from app.db.session import engine
from app.models.entities import AdminUser, RegularUser


async def create_db_and_tables() -> None:
    settings = get_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


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
