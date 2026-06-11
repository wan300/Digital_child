from __future__ import annotations

from dataclasses import dataclass

from app.models.entities import AdminUser

AUTH_DISABLED_USERNAME = "admin"
AUTH_DISABLED_ROLE = "admin"

# Runtime auth is intentionally disabled for the current local deployment.
# Keep the previous JWT/user-table flow in this file as comments so role-based
# auth can be restored without hunting through the route modules.
#
# from fastapi import Depends, HTTPException, status
# from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
# from sqlalchemy import select
# from sqlalchemy.ext.asyncio import AsyncSession
#
# from app.core.security import decode_access_token
# from app.db.session import get_session
#
# bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class AuthenticatedUser:
    username: str
    role: str


async def get_current_user() -> AuthenticatedUser:
    return AuthenticatedUser(username=AUTH_DISABLED_USERNAME, role=AUTH_DISABLED_ROLE)


# Previous JWT-backed implementation:
#
# async def get_current_user(
#     credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
#     session: AsyncSession = Depends(get_session),
# ) -> AuthenticatedUser:
#     if credentials is None:
#         raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
#     try:
#         payload = decode_access_token(credentials.credentials)
#         username = payload.get("sub")
#         role = payload.get("role")
#     except Exception as exc:
#         raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from exc
#     if not username:
#         raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
#
#     if role in (None, "admin"):
#         admin = (await session.execute(select(AdminUser).where(AdminUser.username == username))).scalar_one_or_none()
#         if admin is not None and not admin.disabled:
#             return AuthenticatedUser(username=admin.username, role="admin")
#         if role == "admin":
#             raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid user")
#
#     regular = (await session.execute(select(RegularUser).where(RegularUser.username == username))).scalar_one_or_none()
#     if regular is None or regular.disabled:
#         raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid user")
#     return AuthenticatedUser(username=regular.username, role="user")


async def get_current_admin() -> AdminUser:
    return AdminUser(id="auth-disabled-admin", username=AUTH_DISABLED_USERNAME, password_hash="auth-disabled")


# Previous admin-only implementation:
#
# async def get_current_admin(
#     credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
#     session: AsyncSession = Depends(get_session),
# ) -> AdminUser:
#     if credentials is None:
#         raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
#     try:
#         payload = decode_access_token(credentials.credentials)
#         username = payload.get("sub")
#     except Exception as exc:
#         raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from exc
#     user = (await session.execute(select(AdminUser).where(AdminUser.username == username))).scalar_one_or_none()
#     if user is None or user.disabled:
#         raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid user")
#     return user
