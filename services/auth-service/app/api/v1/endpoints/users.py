"""
Uses platform_auth for the dependency chain, but still needs a DB
lookup here specifically AuthenticatedUser (from the JWT) only
carries id/role/scopes, not the full profile (email, created_at, etc.)
that UserOut returns. This is the one place in auth-service where an
incoming-request dependency and a DB read meet.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from platform_auth import AuthenticatedUser, require_role, require_scopes
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session
from app.repositories.user_repository import UserRepository
from app.schemas.user import UserOut

router = APIRouter(prefix="/users", tags=["users"])


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
