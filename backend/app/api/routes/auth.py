from fastapi import APIRouter, Depends

from app.api.deps import AuthenticatedUser, get_current_user
from app.schemas.api import AdminUserResponse, LoginRequest, TokenResponse

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
async def login(_: LoginRequest) -> TokenResponse:
    # Auth is disabled. This compatibility endpoint does not verify credentials
    # and does not mint a JWT; route dependencies ignore Authorization entirely.
    #
    # Previous behavior:
    #   1. Look up AdminUser, verify password, return role=admin JWT.
    #   2. Else look up RegularUser, verify password, return role=user JWT.
    #   3. Reject invalid credentials with 401.
    return TokenResponse(access_token="auth-disabled")


@router.post("/logout")
async def logout(_: AuthenticatedUser = Depends(get_current_user)) -> dict[str, str]:
    return {"status": "ok"}


@router.get("/me", response_model=AdminUserResponse)
async def me(user: AuthenticatedUser = Depends(get_current_user)) -> AdminUserResponse:
    return AdminUserResponse(username=user.username, role=user.role)
