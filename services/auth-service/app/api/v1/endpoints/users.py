"""
Uses platform_auth for the dependency chain, but still needs a DB
lookup here specifically AuthenticatedUser (from the JWT) only
carries id/role/scopes, not the full profile (email, created_at, etc.)
that UserOut returns. This is the one place in auth-service where an
incoming-request dependency and a DB read meet.
"""
import uuid
from fastapi import APIRouter, Depends, HTTPException, Request, status
from platform_auth import AuthenticatedUser, require_role, require_scopes
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session
from app.repositories.user_repository import UserRepository
from app.repositories.refresh_token_repository import RefreshTokenRepository
from app.schemas.user import UserOut
from app.services.auth_service import AuthService

router = APIRouter(prefix="/users", tags=["users"])

def get_auth_service(request: Request, session: AsyncSession = Depends(get_db_session)) -> AuthService:
    return AuthService(
        UserRepository(session), RefreshTokenRepository(session), request.app.state.user_event_publisher
    )


@router.get("/me", response_model=UserOut)
async def read_current_user(
    current_user: AuthenticatedUser = Depends(require_scopes()),
    session: AsyncSession = Depends(get_db_session),
):
    user = await UserRepository(session).get_by_id(current_user.id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


@router.get("/admin-only", response_model=UserOut)
async def admin_only_example(
    current_user: AuthenticatedUser = Depends(require_role("admin")),
    session: AsyncSession = Depends(get_db_session),
):
    user = await UserRepository(session).get_by_id(current_user.id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


@router.post("/me/deactivate", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_self(
    current_user: AuthenticatedUser = Depends(require_scopes()),
    service: AuthService = Depends(get_auth_service),
):
    await service.deactivate_user(uuid.UUID(current_user.id))


@router.patch("/{user_id}/deactivate", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_user_admin(
    user_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(require_role("admin")),
    service: AuthService = Depends(get_auth_service),
):
    await service.deactivate_user(user_id)


@router.patch("/{user_id}/reactivate", response_model=UserOut)
async def reactivate_user_admin(
    user_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(require_role("admin")),
    service: AuthService = Depends(get_auth_service),
):
    return await service.reactivate_user(user_id)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user_admin(
    user_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(require_role("admin")),
    service: AuthService = Depends(get_auth_service),
):
    await service.delete_user(user_id)