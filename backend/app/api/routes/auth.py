from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthenticatedUser, get_current_user
from app.core.security import create_access_token, verify_password
from app.db.session import get_session
from app.models.entities import AdminUser, RegularUser
from app.schemas.api import AdminUserResponse, LoginRequest, TokenResponse

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, session: AsyncSession = Depends(get_session)) -> TokenResponse:
    admin = (await session.execute(select(AdminUser).where(AdminUser.username == payload.username))).scalar_one_or_none()
    if admin is not None and not admin.disabled and verify_password(payload.password, admin.password_hash):
        return TokenResponse(access_token=create_access_token(admin.username, {"role": "admin"}))

    user = (await session.execute(select(RegularUser).where(RegularUser.username == payload.username))).scalar_one_or_none()
    if user is None or user.disabled or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")
    return TokenResponse(access_token=create_access_token(user.username, {"role": "user"}))


@router.post("/logout")
async def logout(_: AuthenticatedUser = Depends(get_current_user)) -> dict[str, str]:
    return {"status": "ok"}


@router.get("/me", response_model=AdminUserResponse)
async def me(user: AuthenticatedUser = Depends(get_current_user)) -> AdminUserResponse:
    return AdminUserResponse(username=user.username, role=user.role)
