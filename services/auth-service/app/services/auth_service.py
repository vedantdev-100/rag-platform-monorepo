"""
Auth business logic. Framework-agnostic on purpose: no FastAPI imports here,
so this service could be reused by a CLI admin tool or a background worker.
Raises domain exceptions (app.exceptions) — never HTTPException.
"""
from app.core.security import (
    create_access_token,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    refresh_token_expiry,
    verify_password,
    verify_refresh_token,
)
from app.exceptions import (
    InvalidCredentialsError,
    # InvalidTokenError,
    UserAlreadyExistsError,
)
from platform_auth.exceptions import InvalidTokenError, TokenExpiredError

from app.logging import get_logger
from app.models.refresh_token import RefreshToken
from app.models.user import User
from app.repositories.refresh_token_repository import RefreshTokenRepository
from app.repositories.user_repository import UserRepository
from app.schemas.auth import TokenResponse
from app.utils import utcnow

logger = get_logger(__name__)


class AuthService:
    def __init__(self, user_repo: UserRepository, token_repo: RefreshTokenRepository):
        self.user_repo = user_repo
        self.token_repo = token_repo

    async def register(self, email: str, password: str, full_name: str | None) -> User:
        existing = await self.user_repo.get_by_email(email)
        if existing:
            raise UserAlreadyExistsError(f"User with email {email} already exists")

        user = User(
            email=email,
            hashed_password=hash_password(password),
            full_name=full_name,
            role="user",
            scopes="rag:query,rag:ingest",  # a registered user can both query and ingest their own docs
        )
        created = await self.user_repo.create(user)
        logger.info("user_registered", user_id=str(created.id))
        return created

    async def create_superuser(
        self, email: str, password: str, full_name: str | None = None
    ) -> User:
        """
        Django `createsuperuser`-equivalent. Only ever invoked from
        app/cli/create_superuser.py (a trusted, operator-run CLI) — never
        exposed as an API endpoint, since a public "make me admin" route
        would defeat the point of RBAC.
        """
        existing = await self.user_repo.get_by_email(email)
        if existing:
            raise UserAlreadyExistsError(f"User with email {email} already exists")

        user = User(
            email=email,
            hashed_password=hash_password(password),
            full_name=full_name,
            role="admin",
            scopes="rag:query,rag:ingest",  # this deployment is RAG-only; no agent:* scopes here
            is_verified=True,
        )
        created = await self.user_repo.create(user)
        logger.info("superuser_created", user_id=str(created.id))
        return created

    async def login(self, email: str, password: str) -> TokenResponse:
        user = await self.user_repo.get_by_email(email)
        if not user or not verify_password(password, user.hashed_password):
            # Deliberately identical error for "no such user" and "wrong
            # password" — prevents user-enumeration via error messages.
            # Log the raw reason internally without leaking it to the client.
            logger.warning("login_failed", email=email)
            raise InvalidCredentialsError("Invalid email or password")
        if not user.is_active:
            logger.warning("login_failed_inactive_account", user_id=str(user.id))
            raise InvalidCredentialsError("Account is disabled")

        logger.info("login_succeeded", user_id=str(user.id))
        return await self._issue_tokens(user)

    async def refresh(self, plain_refresh_token: str) -> TokenResponse:
        # We can't index by hash directly (bcrypt hashes are salted/non-deterministic),
        # so in production swap this for a lookup-by-token-id pattern (store a
        # short random `token_id` alongside the hash and send "id.secret" to
        # the client). Kept simple here for clarity of the auth flow.
        candidates = await self._find_all_active_tokens()
        matched: RefreshToken | None = None
        for candidate in candidates:
            if verify_refresh_token(plain_refresh_token, candidate.token_hash):
                matched = candidate
                break

        if not matched:
            logger.warning("refresh_token_rejected", reason="not_found_or_revoked")
            raise InvalidTokenError("Refresh token not recognized or already revoked")
        if self.token_repo.is_expired(matched):
            logger.warning("refresh_token_rejected", reason="expired", user_id=str(matched.user_id))
            raise TokenExpiredError("Refresh token expired, please log in again")

        # Rotation: revoke the used token immediately, issue a brand new pair.
        await self.token_repo.revoke(matched)
        user = await self.user_repo.get_by_id(matched.user_id)
        logger.info("access_token_refreshed", user_id=str(user.id))
        return await self._issue_tokens(user)

    async def logout(self, plain_refresh_token: str) -> None:
        candidates = await self._find_all_active_tokens()
        for candidate in candidates:
            if verify_refresh_token(plain_refresh_token, candidate.token_hash):
                await self.token_repo.revoke(candidate)
                logger.info("user_logged_out", user_id=str(candidate.user_id))
                return

    async def _issue_tokens(self, user: User) -> TokenResponse:
        access_token = create_access_token(
            subject=str(user.id), role=user.role, scopes=user.scope_list()
        )
        raw_refresh = generate_refresh_token()
        refresh_record = RefreshToken(
            user_id=user.id,
            token_hash=hash_refresh_token(raw_refresh),
            expires_at=refresh_token_expiry(),
            created_at=utcnow(),
        )
        await self.token_repo.create(refresh_record)

        from app.core.config import get_settings
        settings = get_settings()
        return TokenResponse(
            access_token=access_token,
            refresh_token=raw_refresh,
            expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        )

    async def _find_all_active_tokens(self) -> list[RefreshToken]:
        # NOTE: placeholder full-scan for demo clarity — see production note
        # above re: token_id-prefixed lookup to avoid scanning all tokens.
        from sqlalchemy import select
        result = await self.token_repo.session.execute(
            select(RefreshToken).where(RefreshToken.revoked.is_(False))
        )
        return list(result.scalars().all())
