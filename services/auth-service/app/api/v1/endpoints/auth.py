from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.rate_limit import limiter
from app.db.session import get_db_session
from app.repositories.refresh_token_repository import RefreshTokenRepository
from app.repositories.user_repository import UserRepository
from app.schemas.auth import (
    LoginRequest,
    LogoutRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
)
from app.schemas.user import UserOut
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])
settings = get_settings()

def get_auth_service(session: AsyncSession = Depends(get_db_session)) -> AuthService:
    return AuthService(UserRepository(session), RefreshTokenRepository(session))


# NOTE: no try/except here for InvalidCredentialsError, UserAlreadyExistsError,
# InvalidTokenError, TokenExpiredError, etc. — they're AppError subclasses,
# and app.exceptions.handlers.register_exception_handlers (wired in main.py)
# translates them to the correct HTTP status centrally. Keep it that way;
# don't reintroduce per-endpoint try/except for domain errors.


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
@limiter.limit(settings.RATE_LIMIT_REGISTER)  # bcrypt hashing on every call — cheap to spam otherwise
async def register(
    request: Request,
    payload: RegisterRequest,
    service: AuthService = Depends(get_auth_service),
):
    return await service.register(payload.email, payload.password, payload.full_name)


@router.post("/login", response_model=TokenResponse)
@limiter.limit(settings.RATE_LIMIT_LOGIN)  # brute-force protection on the auth endpoint
async def login(
    request: Request,
    payload: LoginRequest,
    service: AuthService = Depends(get_auth_service),
):
    return await service.login(payload.email, payload.password)


@router.post("/refresh", response_model=TokenResponse)
@limiter.limit(settings.RATE_LIMIT_REFRESH)  # most expensive endpoint to abuse — see AuthService._find_all_active_tokens
async def refresh(
    request: Request,
    payload: RefreshRequest,
    service: AuthService = Depends(get_auth_service),
):
    return await service.refresh(payload.refresh_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit(settings.RATE_LIMIT_LOGOUT)
async def logout(
    request: Request,
    payload: LogoutRequest,
    service: AuthService = Depends(get_auth_service),
):
    await service.logout(payload.refresh_token)
    return None
