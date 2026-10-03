#!/usr/bin/env python3
"""
create_monorepo_structure.py

Run ONCE from an empty directory to scaffold the microservices monorepo:

    python create_monorepo_structure.py

What it does:
  1. Creates every directory and __init__.py needed for three Python
     packages: packages/platform-auth, services/auth-service,
     services/rag-service.
  2. Writes full content for every file that is NEW or CHANGED compared to
     the monolith (platform-auth's entire package, both services' main.py/
     config.py/pyproject.toml/.env.example/Dockerfile, the JWKS endpoint,
     and the two endpoint files whose only change is an import swap).
  3. Leaves files that are copied UNCHANGED from the existing monolith
     (ai-platform) as empty placeholders, and prints + writes
     MIGRATION_CHECKLIST.md listing the exact source -> destination path
     for every one of them, so nothing is forgotten.
  4. Writes k8s/ manifests and a root README.md.

Requires only the Python standard library — nothing to `pip install` to
run this script itself.

Do you need `uv init`? No. This script already writes a complete
pyproject.toml into each service and into the shared package, so `uv init`
would just overwrite work this script already did. What you DO need to run
after this script, per package (see "Next steps" printed at the end):
    uv lock && uv sync
That's `uv`'s normal "install from pyproject.toml" step — unrelated to
`uv init`, which is only for starting a pyproject.toml from scratch.
"""
import textwrap
from pathlib import Path

ROOT = Path(".").resolve()

# ===========================================================================
# Helpers
# ===========================================================================

FILES: dict[str, str] = {}      # path -> full content, written verbatim
EMPTY_DIRS_WITH_INIT: list[str] = []   # Python packages with no new file yet
COPY_MAP: list[tuple[str, str]] = []   # (monolith_source, new_destination) — copy unchanged


def f(path: str, content: str) -> None:
    FILES[path] = textwrap.dedent(content).lstrip("\n")


def pkg(path: str) -> None:
    """Mark a directory as a Python package needing only __init__.py so far."""
    EMPTY_DIRS_WITH_INIT.append(path)


def copy_unchanged(monolith_src: str, dest: str) -> None:
    COPY_MAP.append((monolith_src, dest))
    # Still ensure the destination's parent package directories exist.
    parent = str(Path(dest).parent)
    if parent not in EMPTY_DIRS_WITH_INIT and (parent + "/__init__.py") not in FILES:
        pkg(parent)


# ===========================================================================
# 1. packages/platform-auth
# ===========================================================================

f("packages/platform-auth/pyproject.toml", '''
    [project]
    name = "platform-auth"
    version = "1.0.0"
    description = "Shared JWT verification + RBAC for all services in this platform"
    requires-python = "==3.12.*"
    dependencies = [
        "fastapi==0.115.0",
        "python-jose[cryptography]==3.3.0",
        "httpx==0.27.2",
        "structlog==24.4.0",
    ]

    [project.optional-dependencies]
    # Only services that need instant token revocation install this extra.
    redis = ["redis==5.0.8"]

    [tool.uv]
    resolution = "highest"
    prerelease = "disallow"
    exclude-newer = "7 days"
''')

f("packages/platform-auth/README.md", '''
    # platform-auth

    Shared, installable package every service in this platform depends on
    for JWT verification and RBAC. It does NOT contain token-issuing logic
    (no private key, no login/register) — only auth-service does that.

    ## Install

    Git dependency (fastest to start):
    ```toml
    dependencies = ["platform-auth @ git+https://github.com/yourorg/platform-auth.git@v1.0.0"]
    ```

    Once stable, switch to a private package index (GitHub Packages, AWS
    CodeArtifact) and pin a plain version instead — proper `uv.lock`
    resolution, no full git history on every install.

    ## Use

    ```python
    # main.py
    from platform_auth import setup_auth
    app = FastAPI()
    setup_auth(app)
    ```

    ```python
    # any endpoint
    from platform_auth import require_scopes, AuthenticatedUser

    @router.post("/documents")
    async def upload(current_user: AuthenticatedUser = Depends(require_scopes("rag:ingest"))):
        ...
    ```
''')

f("packages/platform-auth/platform_auth/config.py", '''
    from pydantic import Field
    from pydantic_settings import BaseSettings, SettingsConfigDict


    class PlatformAuthSettings(BaseSettings):
        model_config = SettingsConfigDict(env_prefix="PLATFORM_AUTH_", extra="ignore")

        JWKS_URL: str = Field(..., description="e.g. http://auth-service/.well-known/jwks.json")
        JWKS_CACHE_TTL_SECONDS: int = 900  # 15 min
        JWT_ALGORITHM: str = "RS256"

        # Optional: enables instant-revocation checks (needs the [redis] extra).
        REDIS_URL: str | None = None
''')

f("packages/platform-auth/platform_auth/exceptions.py", '''
    """
    Every service that depends on this package gets the same exception
    types and the same HTTP mapping for them — one place to fix a status
    code, not N places.
    """
    from fastapi import FastAPI, Request, status
    from fastapi.responses import JSONResponse


    class AppError(Exception):
        def __init__(self, message: str):
            self.message = message
            super().__init__(message)


    class InvalidTokenError(AppError):
        pass


    class TokenExpiredError(AppError):
        pass


    class InsufficientPermissionsError(AppError):
        pass


    _STATUS_MAP = {
        InvalidTokenError: status.HTTP_401_UNAUTHORIZED,
        TokenExpiredError: status.HTTP_401_UNAUTHORIZED,
        InsufficientPermissionsError: status.HTTP_403_FORBIDDEN,
    }


    def register_auth_exception_handlers(app: FastAPI) -> None:
        @app.exception_handler(AppError)
        async def _handler(request: Request, exc: AppError):
            code = _STATUS_MAP.get(type(exc), status.HTTP_400_BAD_REQUEST)
            headers = {"WWW-Authenticate": "Bearer"} if code == 401 else None
            return JSONResponse(status_code=code, content={"detail": exc.message}, headers=headers)
''')

f("packages/platform-auth/platform_auth/models.py", '''
    """
    Deliberately NOT a database model. A consuming service never queries
    the users table — everything it needs about the caller comes straight
    from the token's own claims.
    """
    from dataclasses import dataclass


    @dataclass
    class AuthenticatedUser:
        id: str
        role: str
        scopes: list[str]

        def has_scope(self, scope: str) -> bool:
            return self.role == "admin" or scope in self.scopes
''')

f("packages/platform-auth/platform_auth/jwks.py", '''
    """
    Fetches and caches auth-service's public signing keys by `kid`. This is
    what makes key rotation dynamic: auth-service can add a new key without
    any consuming service being redeployed — the cache just misses once,
    refetches, and picks up the new key.
    """
    import time

    import httpx

    from platform_auth.config import PlatformAuthSettings
    from platform_auth.exceptions import InvalidTokenError


    class JWKSClient:
        def __init__(self, settings: PlatformAuthSettings):
            self._settings = settings
            self._keys: dict[str, dict] = {}
            self._fetched_at: float = 0.0

        async def _refresh(self) -> None:
            async with httpx.AsyncClient(timeout=5) as client:
                response = await client.get(self._settings.JWKS_URL)
                response.raise_for_status()
            self._keys = {key["kid"]: key for key in response.json()["keys"]}
            self._fetched_at = time.monotonic()

        async def get_key(self, kid: str | None) -> dict:
            if kid is None:
                raise InvalidTokenError("Token has no key ID (kid)")

            stale = (time.monotonic() - self._fetched_at) > self._settings.JWKS_CACHE_TTL_SECONDS
            if kid not in self._keys or stale:
                await self._refresh()

            if kid not in self._keys:
                raise InvalidTokenError(f"Unknown signing key: {kid!r}")
            return self._keys[kid]
''')

f("packages/platform-auth/platform_auth/tokens.py", '''
    from jose import JWTError, jwt
    from jose.exceptions import ExpiredSignatureError

    from platform_auth.exceptions import InvalidTokenError, TokenExpiredError
    from platform_auth.jwks import JWKSClient


    async def decode_access_token(token: str, jwks_client: JWKSClient) -> dict:
        try:
            header = jwt.get_unverified_header(token)
        except JWTError as exc:
            raise InvalidTokenError("Malformed token") from exc

        jwk = await jwks_client.get_key(header.get("kid"))

        try:
            payload = jwt.decode(token, jwk, algorithms=["RS256"])
        except ExpiredSignatureError as exc:
            raise TokenExpiredError("Access token expired") from exc
        except JWTError as exc:
            raise InvalidTokenError("Invalid token signature") from exc

        if payload.get("type") != "access":
            raise InvalidTokenError("Not an access token")
        return payload
''')

f("packages/platform-auth/platform_auth/blacklist.py", '''
    """
    Instant-revocation check: on logout/refresh, auth-service writes the
    old token's jti to this Redis set (TTL = remaining token lifetime).
    Every consuming service checks it here before trusting an otherwise-
    valid token.
    """
    from platform_auth.config import PlatformAuthSettings


    class TokenBlacklist:
        def __init__(self, settings: PlatformAuthSettings):
            if not settings.REDIS_URL:
                self._redis = None
                return
            import redis.asyncio as redis
            self._redis = redis.from_url(settings.REDIS_URL)

        async def is_revoked(self, jti: str) -> bool:
            if self._redis is None:
                return False  # blacklist not configured — accept token as valid
            return bool(await self._redis.exists(f"revoked:{jti}"))
''')

f("packages/platform-auth/platform_auth/dependencies.py", '''
    from fastapi import Depends, Request
    from fastapi.security import OAuth2PasswordBearer

    from platform_auth.blacklist import TokenBlacklist
    from platform_auth.exceptions import InsufficientPermissionsError, InvalidTokenError
    from platform_auth.models import AuthenticatedUser
    from platform_auth.tokens import decode_access_token

    oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)


    def get_current_user_dependency():
        """
        Factory, not a bare function — setup_auth() calls this once at
        startup with the service's own JWKSClient/TokenBlacklist instances
        (stashed on app.state) and gets back a ready-to-use dependency.
        """
        async def _dependency(request: Request, token: str | None = Depends(oauth2_scheme)) -> AuthenticatedUser:
            if token is None:
                raise InvalidTokenError("Missing Authorization header")
            payload = await decode_access_token(token, request.app.state.jwks_client)

            blacklist: TokenBlacklist = request.app.state.token_blacklist
            if await blacklist.is_revoked(payload.get("jti", "")):
                raise InvalidTokenError("Token has been revoked")

            return AuthenticatedUser(id=payload["sub"], role=payload["role"], scopes=payload.get("scopes", []))

        return _dependency


    def require_scopes(*required_scopes: str):
        def _factory(current_user: AuthenticatedUser = Depends(get_current_user_dependency())) -> AuthenticatedUser:
            if not all(current_user.has_scope(s) for s in required_scopes):
                raise InsufficientPermissionsError(f"Missing required scope(s): {', '.join(required_scopes)}")
            return current_user
        return _factory


    def require_role(*allowed_roles: str):
        def _factory(current_user: AuthenticatedUser = Depends(get_current_user_dependency())) -> AuthenticatedUser:
            if current_user.role not in allowed_roles:
                raise InsufficientPermissionsError("You do not have permission to perform this action")
            return current_user
        return _factory
''')

f("packages/platform-auth/platform_auth/middleware.py", '''
    import uuid

    import structlog
    from fastapi import Request


    async def add_request_id(request: Request, call_next):
        request_id = str(uuid.uuid4())
        structlog.contextvars.bind_contextvars(request_id=request_id)
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response
''')

f("packages/platform-auth/platform_auth/__init__.py", '''
    """
    Everything a consuming service needs to do, in main.py:

        from platform_auth import setup_auth
        setup_auth(app)
    """
    from fastapi import FastAPI

    from platform_auth.blacklist import TokenBlacklist
    from platform_auth.config import PlatformAuthSettings
    from platform_auth.dependencies import require_role, require_scopes
    from platform_auth.exceptions import register_auth_exception_handlers
    from platform_auth.jwks import JWKSClient
    from platform_auth.middleware import add_request_id
    from platform_auth.models import AuthenticatedUser

    __all__ = ["setup_auth", "require_scopes", "require_role", "AuthenticatedUser"]


    def setup_auth(app: FastAPI, settings: PlatformAuthSettings | None = None) -> None:
        settings = settings or PlatformAuthSettings()
        app.state.jwks_client = JWKSClient(settings)
        app.state.token_blacklist = TokenBlacklist(settings)
        app.middleware("http")(add_request_id)
        register_auth_exception_handlers(app)
''')


# ===========================================================================
# 2. services/auth-service — new/changed files
# ===========================================================================

f("services/auth-service/pyproject.toml", '''
    [project]
    name = "auth-service"
    version = "0.1.0"
    description = "Auth microservice: issues and manages JWTs, owns users/refresh_tokens"
    requires-python = "==3.12.*"
    dependencies = [
        "platform-auth @ git+https://github.com/yourorg/platform-auth.git@v1.0.0",
        "fastapi==0.115.0",
        "uvicorn[standard]==0.30.6",
        "pydantic==2.9.2",
        "pydantic-settings==2.5.2",
        "email-validator==2.2.0",
        "sqlalchemy[asyncio]==2.0.35",
        "asyncpg==0.29.0",
        "alembic==1.13.2",
        "passlib[bcrypt]==1.7.4",
        "bcrypt==4.0.1",
        "python-jose[cryptography]==3.3.0",
        "python-multipart==0.0.9",
        "slowapi==0.1.9",
        "structlog==24.4.0",
        "python-dotenv==1.0.1",
        "tenacity==9.0.0",
    ]

    [dependency-groups]
    dev = ["pytest==8.3.3", "pytest-asyncio==0.24.0", "httpx==0.27.2", "ruff==0.7.0", "mypy==1.13.0"]

    [tool.pytest.ini_options]
    asyncio_mode = "strict"
    asyncio_default_fixture_loop_scope = "function"

    [tool.uv]
    resolution = "highest"
    prerelease = "disallow"
    exclude-newer = "7 days"
    default-groups = ["dev"]
''')

f("services/auth-service/.env.example", '''
    APP_NAME=auth-service
    ENVIRONMENT=development
    DEBUG=true
    API_V1_PREFIX=/api/v1
    ALLOWED_ORIGINS=["http://localhost:3000"]

    DATABASE_URL=postgresql+asyncpg://auth_service_role:changeme@localhost:5432/platform?options=-csearch_path=auth

    JWT_PRIVATE_KEY_PATH=./secrets/private_key.pem
    JWT_PUBLIC_KEY_PATH=./secrets/public_key.pem
    JWT_ALGORITHM=RS256
    JWT_KEY_ID=2026-01
    ACCESS_TOKEN_EXPIRE_MINUTES=15
    REFRESH_TOKEN_EXPIRE_DAYS=7

    BCRYPT_ROUNDS=12
    RATE_LIMIT_LOGIN=5/minute
    RATE_LIMIT_REGISTER=3/minute
    RATE_LIMIT_REFRESH=10/minute
    RATE_LIMIT_LOGOUT=10/minute
    RATE_LIMIT_DEFAULT=60/minute

    DB_POOL_SIZE=10
    DB_MAX_OVERFLOW=20
    DB_POOL_TIMEOUT=30
    DB_POOL_RECYCLE=1800

    # auth-service also consumes platform-auth for its own /users/me route.
    PLATFORM_AUTH_JWKS_URL=http://localhost:8000/.well-known/jwks.json
    PLATFORM_AUTH_REDIS_URL=redis://localhost:6379/0
''')

f("services/auth-service/Dockerfile", '''
    FROM python:3.12-slim

    COPY --from=ghcr.io/astral-sh/uv:0.11.7 /uv /uvx /usr/local/bin/
    WORKDIR /code

    RUN apt-get update && apt-get install -y --no-install-recommends gcc libpq-dev git \\
        && rm -rf /var/lib/apt/lists/*

    COPY pyproject.toml uv.lock .python-version ./
    RUN uv sync --locked --no-dev --no-install-project

    COPY . .
    RUN uv sync --locked --no-dev

    EXPOSE 8000
    CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
''')

f("services/auth-service/app/main.py", '''
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware
    from slowapi import _rate_limit_exceeded_handler
    from slowapi.errors import RateLimitExceeded
    from slowapi.middleware import SlowAPIMiddleware
    from platform_auth import setup_auth

    from app.api.v1.endpoints.auth import limiter
    from app.api.v1.router import api_router
    from app.core.config import get_settings
    from app.exceptions import register_exception_handlers
    from app.logging import configure_logging, get_logger

    settings = get_settings()
    configure_logging(debug=settings.DEBUG)
    logger = get_logger(__name__)


    def create_app() -> FastAPI:
        app = FastAPI(
            title=settings.APP_NAME,
            debug=settings.DEBUG,
            docs_url="/docs" if not settings.is_production else None,
            redoc_url=None,
        )

        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.ALLOWED_ORIGINS,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

        app.state.limiter = limiter
        app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
        app.add_middleware(SlowAPIMiddleware)

        # Shared concerns (request-ID middleware, JWT verification for the
        # /users/me route, shared exception types) come from platform_auth.
        setup_auth(app)
        # auth-service's OWN exceptions (InvalidCredentialsError, etc.)
        register_exception_handlers(app, is_production=settings.is_production)

        app.include_router(api_router, prefix=settings.API_V1_PREFIX)

        @app.get("/health")
        async def health_check():
            return {"status": "ok", "environment": settings.ENVIRONMENT}

        return app


    app = create_app()
''')

f("services/auth-service/app/core/config.py", '''
    from functools import lru_cache
    from pathlib import Path
    from typing import List, Literal

    from pydantic_settings import BaseSettings, SettingsConfigDict


    class Settings(BaseSettings):
        model_config = SettingsConfigDict(env_file=".env", extra="ignore")

        APP_NAME: str = "auth-service"
        ENVIRONMENT: Literal["development", "staging", "production"] = "development"
        DEBUG: bool = False
        API_V1_PREFIX: str = "/api/v1"
        ALLOWED_ORIGINS: List[str] = ["http://localhost:3000"]

        DATABASE_URL: str

        JWT_PRIVATE_KEY_PATH: str
        JWT_PUBLIC_KEY_PATH: str
        JWT_ALGORITHM: str = "RS256"
        JWT_KEY_ID: str = "2026-01"  # bump when rotating; must appear in /.well-known/jwks.json
        ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
        REFRESH_TOKEN_EXPIRE_DAYS: int = 7

        BCRYPT_ROUNDS: int = 12
        RATE_LIMIT_LOGIN: str = "5/minute"
        RATE_LIMIT_REGISTER: str = "3/minute"
        RATE_LIMIT_REFRESH: str = "10/minute"
        RATE_LIMIT_LOGOUT: str = "10/minute"
        RATE_LIMIT_DEFAULT: str = "60/minute"

        DB_POOL_SIZE: int = 10
        DB_MAX_OVERFLOW: int = 20
        DB_POOL_TIMEOUT: int = 30
        DB_POOL_RECYCLE: int = 1800

        @property
        def jwt_private_key(self) -> str:
            return Path(self.JWT_PRIVATE_KEY_PATH).read_text()

        @property
        def jwt_public_key(self) -> str:
            return Path(self.JWT_PUBLIC_KEY_PATH).read_text()

        @property
        def is_production(self) -> bool:
            return self.ENVIRONMENT == "production"


    @lru_cache
    def get_settings() -> Settings:
        return Settings()
''')

f("services/auth-service/app/api/v1/endpoints/well_known.py", '''
    """
    JWKS endpoint — what makes key rotation dynamic. Every other service's
    platform_auth.JWKSClient fetches and caches this; add a new key here
    (bump JWT_KEY_ID + keep the old key available until its longest-lived
    token expires) and no consuming service needs to redeploy.
    """
    from cryptography.hazmat.primitives import serialization
    from fastapi import APIRouter
    from jose.utils import base64url_encode

    from app.core.config import get_settings

    router = APIRouter(tags=["well-known"])
    settings = get_settings()


    @router.get("/.well-known/jwks.json")
    async def jwks():
        public_key = serialization.load_pem_public_key(settings.jwt_public_key.encode())
        numbers = public_key.public_numbers()
        n = numbers.n.to_bytes((numbers.n.bit_length() + 7) // 8, "big")
        e = numbers.e.to_bytes((numbers.e.bit_length() + 7) // 8, "big")
        return {
            "keys": [{
                "kty": "RSA", "use": "sig", "alg": settings.JWT_ALGORITHM, "kid": settings.JWT_KEY_ID,
                "n": base64url_encode(n).decode(), "e": base64url_encode(e).decode(),
            }]
        }
''')

f("services/auth-service/app/api/v1/endpoints/users.py", '''
    """
    Uses platform_auth for the dependency chain, but still needs a DB
    lookup here specifically — AuthenticatedUser (from the JWT) only
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
''')

f("services/auth-service/app/exceptions/base.py", '''
    """auth-service's OWN exceptions only — InvalidTokenError, TokenExpiredError,
    and InsufficientPermissionsError now live in platform_auth and are
    registered by setup_auth() in main.py, not here."""


    class AppError(Exception):
        def __init__(self, message: str):
            self.message = message
            super().__init__(message)


    class InvalidCredentialsError(AppError):
        pass


    class UserAlreadyExistsError(AppError):
        pass


    class UserNotFoundError(AppError):
        pass
''')

f("services/auth-service/app/exceptions/handlers.py", '''
    from fastapi import FastAPI, Request, status
    from fastapi.responses import JSONResponse

    from app.exceptions.base import AppError, InvalidCredentialsError, UserAlreadyExistsError, UserNotFoundError
    from app.logging import get_logger

    logger = get_logger(__name__)

    _STATUS_MAP = {
        InvalidCredentialsError: status.HTTP_401_UNAUTHORIZED,
        UserAlreadyExistsError: status.HTTP_409_CONFLICT,
        UserNotFoundError: status.HTTP_404_NOT_FOUND,
    }


    def register_exception_handlers(app: FastAPI, *, is_production: bool) -> None:
        @app.exception_handler(AppError)
        async def app_error_handler(request: Request, exc: AppError):
            status_code = _STATUS_MAP.get(type(exc), status.HTTP_400_BAD_REQUEST)
            headers = {"WWW-Authenticate": "Bearer"} if status_code == 401 else None
            return JSONResponse(status_code=status_code, content={"detail": exc.message}, headers=headers)

        @app.exception_handler(Exception)
        async def unhandled_exception_handler(request: Request, exc: Exception):
            logger.error("unhandled_exception", error=str(exc), path=request.url.path)
            return JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content={"detail": "Internal server error"} if is_production else {"detail": str(exc)},
            )
''')

f("services/auth-service/app/exceptions/__init__.py", '''
    from app.exceptions.base import AppError, InvalidCredentialsError, UserAlreadyExistsError, UserNotFoundError
    from app.exceptions.handlers import register_exception_handlers

    __all__ = [
        "AppError", "InvalidCredentialsError", "UserAlreadyExistsError",
        "UserNotFoundError", "register_exception_handlers",
    ]
''')

f("services/auth-service/app/api/v1/router.py", '''
    from fastapi import APIRouter

    from app.api.v1.endpoints import auth, users, well_known

    api_router = APIRouter()
    api_router.include_router(auth.router)
    api_router.include_router(users.router)
    api_router.include_router(well_known.router)
''')

# Files copied UNCHANGED from the monolith (ai-platform) into auth-service.
copy_unchanged("app/core/security.py", "services/auth-service/app/core/security.py")  # add kid+JWT_KEY_ID header — see note below
copy_unchanged("app/db/base.py", "services/auth-service/app/db/base.py")
copy_unchanged("app/db/session.py", "services/auth-service/app/db/session.py")
copy_unchanged("app/models/user.py", "services/auth-service/app/models/user.py")
copy_unchanged("app/models/refresh_token.py", "services/auth-service/app/models/refresh_token.py")
copy_unchanged("app/repositories/user_repository.py", "services/auth-service/app/repositories/user_repository.py")
copy_unchanged("app/repositories/refresh_token_repository.py", "services/auth-service/app/repositories/refresh_token_repository.py")
copy_unchanged("app/schemas/auth.py", "services/auth-service/app/schemas/auth.py")
copy_unchanged("app/schemas/user.py", "services/auth-service/app/schemas/user.py")
copy_unchanged("app/services/auth_service.py", "services/auth-service/app/services/auth_service.py")
copy_unchanged("app/logging/config.py", "services/auth-service/app/logging/config.py")
copy_unchanged("app/logging/__init__.py", "services/auth-service/app/logging/__init__.py")  # trim: drop add_request_id export, platform_auth provides it now
copy_unchanged("app/utils/datetime_utils.py", "services/auth-service/app/utils/datetime_utils.py")
copy_unchanged("app/utils/id_utils.py", "services/auth-service/app/utils/id_utils.py")
copy_unchanged("app/utils/pagination.py", "services/auth-service/app/utils/pagination.py")
copy_unchanged("app/utils/__init__.py", "services/auth-service/app/utils/__init__.py")
copy_unchanged("app/cli/create_superuser.py", "services/auth-service/app/cli/create_superuser.py")
copy_unchanged("app/api/v1/endpoints/auth.py", "services/auth-service/app/api/v1/endpoints/auth.py")
copy_unchanged("alembic/env.py", "services/auth-service/alembic/env.py")  # trim model imports to user, refresh_token only
copy_unchanged("alembic/script.py.mako", "services/auth-service/alembic/script.py.mako")
copy_unchanged("alembic.ini", "services/auth-service/alembic.ini")

for d in ["services/auth-service/app", "services/auth-service/app/core", "services/auth-service/app/db",
          "services/auth-service/app/models", "services/auth-service/app/repositories",
          "services/auth-service/app/schemas", "services/auth-service/app/services",
          "services/auth-service/app/exceptions", "services/auth-service/app/logging",
          "services/auth-service/app/utils", "services/auth-service/app/cli",
          "services/auth-service/app/api", "services/auth-service/app/api/v1",
          "services/auth-service/app/api/v1/endpoints", "services/auth-service/app/tests",
          "services/auth-service/app/tests/unit", "services/auth-service/app/tests/integration",
          "services/auth-service/alembic/versions"]:
    pkg(d)


# ===========================================================================
# 3. services/rag-service — new/changed files
# ===========================================================================

f("services/rag-service/pyproject.toml", '''
    [project]
    name = "rag-service"
    version = "0.1.0"
    description = "RAG microservice: multimodal ingestion, hybrid retrieval, generation"
    requires-python = "==3.12.*"
    dependencies = [
        "platform-auth @ git+https://github.com/yourorg/platform-auth.git@v1.0.0",
        "fastapi==0.115.0",
        "uvicorn[standard]==0.30.6",
        "pydantic==2.9.2",
        "pydantic-settings==2.5.2",
        "sqlalchemy[asyncio]==2.0.35",
        "asyncpg==0.29.0",
        "alembic==1.13.2",
        "pgvector==0.3.6",
        "docling==2.87.0",
        "docling-core==2.74.0",
        "sentence-transformers==3.3.1",
        "huggingface-hub==0.36.2",
        "aiofiles==24.1.0",
        "httpx==0.27.2",
        "slowapi==0.1.9",
        "structlog==24.4.0",
        "python-dotenv==1.0.1",
        "tenacity==9.0.0",
    ]

    [dependency-groups]
    dev = [
        "pytest==8.3.3", "pytest-asyncio==0.24.0", "ruff==0.7.0", "mypy==1.13.0",
        "transformers==4.57.6", "tokenizers==0.22.2", "python-docx==1.2.0", "pillow==12.3.0",
    ]

    [tool.pytest.ini_options]
    asyncio_mode = "strict"
    asyncio_default_fixture_loop_scope = "function"

    [tool.uv]
    resolution = "highest"
    prerelease = "disallow"
    exclude-newer = "7 days"
    default-groups = ["dev"]
''')

f("services/rag-service/.env.example", '''
    APP_NAME=rag-service
    ENVIRONMENT=development
    DEBUG=true
    API_V1_PREFIX=/api/v1
    ALLOWED_ORIGINS=["http://localhost:3000"]

    DATABASE_URL=postgresql+asyncpg://rag_service_role:changeme@localhost:5432/platform?options=-csearch_path=rag

    RATE_LIMIT_UPLOAD=5/minute
    RATE_LIMIT_SEARCH=20/minute
    RATE_LIMIT_DEFAULT=60/minute

    DB_POOL_SIZE=10
    DB_MAX_OVERFLOW=20
    DB_POOL_TIMEOUT=30
    DB_POOL_RECYCLE=1800

    STORAGE_BACKEND=local
    LOCAL_STORAGE_DIR=./data/uploads
    RAG_MAX_UPLOAD_MB=25
    MODELS_DIR=./models

    RAG_PARSER_BACKEND=docling
    RAG_PARSER_MAX_CONCURRENCY=1
    RAG_DOCLING_LOCAL_MODELS_ONLY=true
    RAG_OCR_ENABLED=true
    RAG_TABLE_STRUCTURE_ENABLED=true

    RAG_PICTURE_DESCRIPTION_ENABLED=false
    RAG_PICTURE_DESCRIPTION_BACKEND=local
    RAG_PICTURE_DESCRIPTION_MODEL=HuggingFaceTB/SmolVLM-256M-Instruct

    RAG_CHUNKER_BACKEND=docling
    RAG_CHUNKER_TOKENIZER=huggingface
    RAG_CHUNKER_TOKENIZER_MODEL=BAAI/bge-base-en-v1.5
    RAG_CHUNKER_MAX_TOKENS=500
    RAG_CHUNKER_MERGE_PEERS=true

    RAG_EMBEDDING_BACKEND=sentence_transformers
    RAG_EMBEDDING_MODEL=BAAI/bge-base-en-v1.5
    EMBEDDING_DIMENSIONS=768

    RAG_RETRIEVER_BACKEND=hybrid
    RAG_RETRIEVAL_CANDIDATES=20
    RAG_RRF_K=60
    RAG_RERANKER_ENABLED=false
    RAG_RERANKER_BACKEND=local
    RAG_RERANKER_MODEL=BAAI/bge-reranker-base
    RAG_RERANKER_TOP_N=5

    # Points at auth-service's cluster-internal DNS name, not a public URL.
    PLATFORM_AUTH_JWKS_URL=http://auth-service.rag-platform.svc.cluster.local/.well-known/jwks.json
    PLATFORM_AUTH_REDIS_URL=redis://redis.rag-platform.svc.cluster.local:6379/0
''')

f("services/rag-service/Dockerfile", '''
    FROM python:3.12-slim

    COPY --from=ghcr.io/astral-sh/uv:0.11.7 /uv /uvx /usr/local/bin/
    WORKDIR /code

    RUN apt-get update && apt-get install -y --no-install-recommends \\
        gcc libpq-dev git libgl1 libglib2.0-0 \\
        && rm -rf /var/lib/apt/lists/*

    COPY pyproject.toml uv.lock .python-version ./
    RUN uv sync --locked --no-dev --no-install-project

    COPY . .
    RUN uv sync --locked --no-dev
    # Bake models into the image for production — avoids first-request
    # latency and flaky runtime downloads:
    # RUN uv run python -m app.cli.download_models

    EXPOSE 8000
    CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
''')

f("services/rag-service/app/main.py", '''
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware
    from slowapi import _rate_limit_exceeded_handler
    from slowapi.errors import RateLimitExceeded
    from slowapi.middleware import SlowAPIMiddleware
    from platform_auth import setup_auth

    from app.api.v1.router import api_router
    from app.core.config import get_settings
    from app.core.rate_limit import limiter
    from app.exceptions import register_exception_handlers
    from app.logging import configure_logging, get_logger

    settings = get_settings()
    configure_logging(debug=settings.DEBUG)
    logger = get_logger(__name__)


    def create_app() -> FastAPI:
        app = FastAPI(
            title=settings.APP_NAME,
            debug=settings.DEBUG,
            docs_url="/docs" if not settings.is_production else None,
            redoc_url=None,
        )

        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.ALLOWED_ORIGINS,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

        app.state.limiter = limiter
        app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
        app.add_middleware(SlowAPIMiddleware)

        # Shared concerns (request-ID middleware, JWT verification, shared
        # exception types) come from platform_auth — no local auth code here.
        setup_auth(app)
        # rag-service's OWN exceptions: IngestionError, ModelNotFoundError, etc.
        register_exception_handlers(app, is_production=settings.is_production)

        app.include_router(api_router, prefix=settings.API_V1_PREFIX)

        @app.get("/health")
        async def health_check():
            return {"status": "ok", "environment": settings.ENVIRONMENT}

        return app


    app = create_app()
''')

f("services/rag-service/app/core/config.py", '''
    """
    No JWT_* fields at all — rag-service never issues or holds signing
    keys. Token verification settings (PLATFORM_AUTH_JWKS_URL, etc.) live
    in platform_auth's own PlatformAuthSettings, read from the same .env
    via the PLATFORM_AUTH_ env prefix.
    """
    from functools import lru_cache
    from typing import List, Literal

    from pydantic import SecretStr, model_validator
    from pydantic_settings import BaseSettings, SettingsConfigDict


    class Settings(BaseSettings):
        model_config = SettingsConfigDict(env_file=".env", extra="ignore")

        APP_NAME: str = "rag-service"
        ENVIRONMENT: Literal["development", "staging", "production"] = "development"
        DEBUG: bool = False
        API_V1_PREFIX: str = "/api/v1"
        ALLOWED_ORIGINS: List[str] = ["http://localhost:3000"]

        DATABASE_URL: str

        RATE_LIMIT_UPLOAD: str = "5/minute"
        RATE_LIMIT_SEARCH: str = "20/minute"
        RATE_LIMIT_DEFAULT: str = "60/minute"

        DB_POOL_SIZE: int = 10
        DB_MAX_OVERFLOW: int = 20
        DB_POOL_TIMEOUT: int = 30
        DB_POOL_RECYCLE: int = 1800

        STORAGE_BACKEND: Literal["local"] = "local"
        LOCAL_STORAGE_DIR: str = "./data/uploads"
        RAG_MAX_UPLOAD_MB: int = 25
        MODELS_DIR: str = "./models"

        RAG_PARSER_BACKEND: Literal["docling"] = "docling"
        RAG_PARSER_MAX_CONCURRENCY: int = 1
        RAG_DOCLING_LOCAL_MODELS_ONLY: bool = True
        RAG_OCR_ENABLED: bool = True
        RAG_TABLE_STRUCTURE_ENABLED: bool = True

        RAG_PICTURE_DESCRIPTION_ENABLED: bool = False
        RAG_PICTURE_DESCRIPTION_BACKEND: Literal["local", "api"] = "local"
        RAG_PICTURE_DESCRIPTION_MODEL: str = "HuggingFaceTB/SmolVLM-256M-Instruct"
        RAG_PICTURE_DESCRIPTION_PROMPT: str = (
            "Describe this image in a few sentences. If it is a chart, graph or diagram, "
            "state its type, axes, series, and the key values and trends."
        )
        RAG_PICTURE_MIN_AREA: float = 0.05
        RAG_PICTURE_DESCRIPTION_API_URL: str = ""
        RAG_PICTURE_DESCRIPTION_API_MODEL: str = ""
        RAG_PICTURE_DESCRIPTION_API_KEY: SecretStr = SecretStr("")
        RAG_PICTURE_DESCRIPTION_TIMEOUT: int = 60

        RAG_CHUNKER_BACKEND: Literal["docling", "simple"] = "docling"
        RAG_CHUNKER_TOKENIZER: Literal["huggingface", "approx"] = "huggingface"
        RAG_CHUNKER_TOKENIZER_MODEL: str = "BAAI/bge-base-en-v1.5"
        RAG_CHUNKER_MAX_TOKENS: int = 500
        RAG_CHUNKER_MERGE_PEERS: bool = True

        RAG_EMBEDDING_BACKEND: Literal["stub", "sentence_transformers"] = "sentence_transformers"
        RAG_EMBEDDING_MODEL: str = "BAAI/bge-base-en-v1.5"
        RAG_EMBEDDING_DEVICE: str | None = None
        RAG_EMBEDDING_BATCH_SIZE: int = 32
        EMBEDDING_DIMENSIONS: int = 768

        RAG_DEFAULT_TOP_K: int = 5
        RAG_CHUNK_SIZE: int = 512
        RAG_CHUNK_OVERLAP: int = 50
        RAG_DISTANCE_METRIC: str = "cosine"
        RAG_HYBRID_VECTOR_WEIGHT: float = 0.5

        RAG_RETRIEVER_BACKEND: Literal["vector", "keyword", "hybrid"] = "hybrid"
        RAG_RETRIEVAL_CANDIDATES: int = 20
        RAG_RRF_K: int = 60

        RAG_RERANKER_ENABLED: bool = False
        RAG_RERANKER_BACKEND: Literal["local", "api"] = "local"
        RAG_RERANKER_TOP_N: int = 5
        RAG_RERANKER_MODEL: str = "BAAI/bge-reranker-base"
        RAG_RERANKER_DEVICE: str | None = None
        RAG_RERANKER_API_PROVIDER: Literal["cohere", "voyage"] = "cohere"
        RAG_RERANKER_API_KEY: SecretStr = SecretStr("")
        RAG_RERANKER_API_MODEL: str = "rerank-english-v3.0"
        RAG_RERANKER_API_TIMEOUT: int = 30

        @model_validator(mode="after")
        def _validate_picture_description(self) -> "Settings":
            if self.RAG_PICTURE_DESCRIPTION_ENABLED and self.RAG_PICTURE_DESCRIPTION_BACKEND == "api":
                missing = [n for n in ("RAG_PICTURE_DESCRIPTION_API_URL", "RAG_PICTURE_DESCRIPTION_API_MODEL") if not getattr(self, n)]
                if missing:
                    raise ValueError(f"RAG_PICTURE_DESCRIPTION_BACKEND=api requires: {', '.join(missing)}")
            return self

        @model_validator(mode="after")
        def _validate_reranker(self) -> "Settings":
            if self.RAG_RERANKER_ENABLED and self.RAG_RERANKER_BACKEND == "api":
                if not self.RAG_RERANKER_API_KEY.get_secret_value():
                    raise ValueError("RAG_RERANKER_BACKEND=api requires RAG_RERANKER_API_KEY")
            return self

        @property
        def is_production(self) -> bool:
            return self.ENVIRONMENT == "production"


    @lru_cache
    def get_settings() -> Settings:
        return Settings()
''')

f("services/rag-service/app/api/v1/endpoints/documents.py", '''
    """Only the auth import changed from the monolith version — the scope
    check itself (`require_scopes("rag:ingest")`) is identical."""
    from pathlib import Path

    from fastapi import APIRouter, Depends, Request, UploadFile
    from platform_auth import AuthenticatedUser, require_scopes
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.core.config import get_settings
    from app.core.rate_limit import limiter
    from app.db.session import get_db_session
    from app.exceptions import FileTooLargeError
    from app.rag.ingestion.factory import get_chunker, get_document_parser, get_embedding_generator, get_file_storage
    from app.rag.ingestion.pipeline import IngestionService
    from app.rag.ingestion.source_types import detect_source_type
    from app.repositories.chunk_repository import ChunkRepository
    from app.repositories.document_repository import DocumentRepository
    from app.schemas.document import DocumentListOut, DocumentOut

    router = APIRouter(prefix="/documents", tags=["documents"])
    settings = get_settings()
    _READ_CHUNK_BYTES = 1024 * 1024


    def get_ingestion_service(session: AsyncSession = Depends(get_db_session)) -> IngestionService:
        return IngestionService(
            storage=get_file_storage(), parser=get_document_parser(), chunker=get_chunker(),
            embedder=get_embedding_generator(), document_repo=DocumentRepository(session),
            chunk_repo=ChunkRepository(session),
        )


    async def _read_capped(file: UploadFile, max_bytes: int) -> bytes:
        data = bytearray()
        while piece := await file.read(_READ_CHUNK_BYTES):
            data.extend(piece)
            if len(data) > max_bytes:
                raise FileTooLargeError(f"File exceeds the {settings.RAG_MAX_UPLOAD_MB} MB upload limit")
        return bytes(data)


    @router.post("", response_model=DocumentOut, status_code=201)
    @limiter.limit(settings.RATE_LIMIT_UPLOAD)
    async def upload_document(
        request: Request,
        file: UploadFile,
        current_user: AuthenticatedUser = Depends(require_scopes("rag:ingest")),
        service: IngestionService = Depends(get_ingestion_service),
    ):
        filename = Path(file.filename or "upload").name
        content = await _read_capped(file, settings.RAG_MAX_UPLOAD_MB * 1024 * 1024)
        return await service.ingest(
            owner_id=current_user.id, filename=filename, content=content,
            source_type=detect_source_type(filename),
        )


    @router.get("", response_model=DocumentListOut)
    async def list_documents(
        current_user: AuthenticatedUser = Depends(require_scopes("rag:query")),
        session: AsyncSession = Depends(get_db_session),
        limit: int = 20,
        offset: int = 0,
    ):
        repo = DocumentRepository(session)
        documents = await repo.list_by_owner(current_user.id, limit=limit, offset=offset)
        return DocumentListOut(documents=documents, total=len(documents))
''')

f("services/rag-service/app/api/v1/endpoints/search.py", '''
    """Only the auth import changed from the version given earlier in chat."""
    from fastapi import APIRouter, Depends, Request
    from platform_auth import AuthenticatedUser, require_scopes
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.core.config import get_settings
    from app.core.rate_limit import limiter
    from app.db.session import get_db_session
    from app.rag.retrieval.factory import get_reranker, get_retriever
    from app.repositories.chunk_repository import ChunkRepository
    from app.schemas.search import SearchRequest, SearchResponse, SearchResultOut

    router = APIRouter(prefix="/documents", tags=["search"])
    settings = get_settings()


    @router.post("/search", response_model=SearchResponse)
    @limiter.limit(settings.RATE_LIMIT_SEARCH)
    async def search_documents(
        request: Request,
        payload: SearchRequest,
        current_user: AuthenticatedUser = Depends(require_scopes("rag:query")),
        session: AsyncSession = Depends(get_db_session),
    ):
        chunk_repo = ChunkRepository(session)
        retriever = get_retriever(chunk_repo)
        reranker = get_reranker()

        candidate_count = settings.RAG_RETRIEVAL_CANDIDATES if reranker else payload.top_k
        results = await retriever.retrieve(payload.query, owner_id=str(current_user.id), top_k=candidate_count)

        reranked = False
        if reranker and results:
            top_n = payload.top_k or settings.RAG_RERANKER_TOP_N
            results = await reranker.rerank(payload.query, results, top_n=top_n)
            reranked = True
        elif payload.top_k:
            results = results[: payload.top_k]

        return SearchResponse(
            query=payload.query,
            results=[SearchResultOut(**r.__dict__) for r in results],
            retriever_backend=settings.RAG_RETRIEVER_BACKEND,
            reranked=reranked,
        )
''')

f("services/rag-service/app/api/v1/router.py", '''
    from fastapi import APIRouter

    from app.api.v1.endpoints import documents, search

    api_router = APIRouter()
    api_router.include_router(documents.router)
    api_router.include_router(search.router)
''')

f("services/rag-service/app/exceptions/base.py", '''
    """rag-service's OWN exceptions only — shared ones live in platform_auth."""


    class AppError(Exception):
        def __init__(self, message: str):
            self.message = message
            super().__init__(message)


    class GuardrailViolationError(AppError):
        pass


    class RetrievalError(AppError):
        pass


    class IngestionError(AppError):
        pass


    class ModelNotFoundError(AppError):
        pass


    class FileTooLargeError(AppError):
        pass
''')

f("services/rag-service/app/exceptions/handlers.py", '''
    from fastapi import FastAPI, Request, status
    from fastapi.responses import JSONResponse

    from app.exceptions.base import (
        AppError, FileTooLargeError, GuardrailViolationError, IngestionError,
        ModelNotFoundError, RetrievalError,
    )
    from app.logging import get_logger

    logger = get_logger(__name__)

    _STATUS_MAP = {
        GuardrailViolationError: status.HTTP_422_UNPROCESSABLE_ENTITY,
        RetrievalError: status.HTTP_502_BAD_GATEWAY,
        IngestionError: status.HTTP_422_UNPROCESSABLE_ENTITY,
        FileTooLargeError: status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
        ModelNotFoundError: status.HTTP_503_SERVICE_UNAVAILABLE,
    }


    def register_exception_handlers(app: FastAPI, *, is_production: bool) -> None:
        @app.exception_handler(AppError)
        async def app_error_handler(request: Request, exc: AppError):
            status_code = _STATUS_MAP.get(type(exc), status.HTTP_400_BAD_REQUEST)
            return JSONResponse(status_code=status_code, content={"detail": exc.message})

        @app.exception_handler(Exception)
        async def unhandled_exception_handler(request: Request, exc: Exception):
            logger.error("unhandled_exception", error=str(exc), path=request.url.path)
            return JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content={"detail": "Internal server error"} if is_production else {"detail": str(exc)},
            )
''')

f("services/rag-service/app/exceptions/__init__.py", '''
    from app.exceptions.base import (
        AppError, FileTooLargeError, GuardrailViolationError, IngestionError,
        ModelNotFoundError, RetrievalError,
    )
    from app.exceptions.handlers import register_exception_handlers

    __all__ = [
        "AppError", "GuardrailViolationError", "RetrievalError", "IngestionError",
        "ModelNotFoundError", "FileTooLargeError", "register_exception_handlers",
    ]
''')

# Files copied UNCHANGED from the monolith into rag-service.
copy_unchanged("app/db/base.py", "services/rag-service/app/db/base.py")
copy_unchanged("app/db/session.py", "services/rag-service/app/db/session.py")
copy_unchanged("app/models/document.py", "services/rag-service/app/models/document.py")
copy_unchanged("app/models/chunk.py", "services/rag-service/app/models/chunk.py")
copy_unchanged("app/repositories/document_repository.py", "services/rag-service/app/repositories/document_repository.py")
copy_unchanged("app/repositories/chunk_repository.py", "services/rag-service/app/repositories/chunk_repository.py")
copy_unchanged("app/schemas/document.py", "services/rag-service/app/schemas/document.py")
copy_unchanged("app/schemas/search.py", "services/rag-service/app/schemas/search.py")
copy_unchanged("app/core/rate_limit.py", "services/rag-service/app/core/rate_limit.py")
copy_unchanged("app/logging/config.py", "services/rag-service/app/logging/config.py")
copy_unchanged("app/logging/__init__.py", "services/rag-service/app/logging/__init__.py")
copy_unchanged("app/utils/datetime_utils.py", "services/rag-service/app/utils/datetime_utils.py")
copy_unchanged("app/utils/id_utils.py", "services/rag-service/app/utils/id_utils.py")
copy_unchanged("app/utils/pagination.py", "services/rag-service/app/utils/pagination.py")
copy_unchanged("app/utils/__init__.py", "services/rag-service/app/utils/__init__.py")
copy_unchanged("app/guardrails/base.py", "services/rag-service/app/guardrails/base.py")
copy_unchanged("app/guardrails/__init__.py", "services/rag-service/app/guardrails/__init__.py")
copy_unchanged("app/cli/download_models.py", "services/rag-service/app/cli/download_models.py")
copy_unchanged("alembic/env.py", "services/rag-service/alembic/env.py")  # trim model imports to document, chunk only
copy_unchanged("alembic/script.py.mako", "services/rag-service/alembic/script.py.mako")
copy_unchanged("alembic.ini", "services/rag-service/alembic.ini")

# Entire ingestion + retrieval subtree — copy the directories as-is.
for sub in [
    "base.py", "source_types.py", "model_paths.py", "storage.py", "factory.py", "pipeline.py",
    "parsers/docling_parser.py", "chunking/tokenizers.py", "chunking/docling_chunker.py",
    "chunking/simple_chunker.py", "embeddings/stub_embedder.py", "embeddings/sentence_transformers_embedder.py",
]:
    copy_unchanged(f"app/rag/ingestion/{sub}", f"services/rag-service/app/rag/ingestion/{sub}")

for sub in [
    "base.py", "vector_retriever.py", "keyword_retriever.py", "hybrid_retriever.py", "factory.py",
    "rerankers/cross_encoder_reranker.py", "rerankers/cohere_reranker.py", "rerankers/voyage_reranker.py",
]:
    copy_unchanged(f"app/rag/retrieval/{sub}", f"services/rag-service/app/rag/retrieval/{sub}")

for d in ["services/rag-service/app", "services/rag-service/app/core", "services/rag-service/app/db",
          "services/rag-service/app/models", "services/rag-service/app/repositories",
          "services/rag-service/app/schemas", "services/rag-service/app/exceptions",
          "services/rag-service/app/logging", "services/rag-service/app/utils",
          "services/rag-service/app/guardrails", "services/rag-service/app/cli",
          "services/rag-service/app/api", "services/rag-service/app/api/v1",
          "services/rag-service/app/api/v1/endpoints", "services/rag-service/app/rag",
          "services/rag-service/app/rag/ingestion", "services/rag-service/app/rag/ingestion/parsers",
          "services/rag-service/app/rag/ingestion/chunking", "services/rag-service/app/rag/ingestion/embeddings",
          "services/rag-service/app/rag/retrieval", "services/rag-service/app/rag/retrieval/rerankers",
          "services/rag-service/app/tests", "services/rag-service/app/tests/unit",
          "services/rag-service/app/tests/integration", "services/rag-service/alembic/versions"]:
    pkg(d)


# ===========================================================================
# 4. k8s/ manifests
# ===========================================================================

f("k8s/namespace.yaml", '''
    apiVersion: v1
    kind: Namespace
    metadata: { name: rag-platform }
''')

f("k8s/postgres.yaml", '''
    apiVersion: apps/v1
    kind: StatefulSet
    metadata: { name: postgres, namespace: rag-platform }
    spec:
      serviceName: postgres
      replicas: 1
      selector: { matchLabels: { app: postgres } }
      template:
        metadata: { labels: { app: postgres } }
        spec:
          containers:
            - name: postgres
              image: pgvector/pgvector:pg16
              envFrom: [{ secretRef: { name: postgres-credentials } }]
              volumeMounts: [{ name: data, mountPath: /var/lib/postgresql/data }]
      volumeClaimTemplates:
        - metadata: { name: data }
          spec: { accessModes: ["ReadWriteOnce"], resources: { requests: { storage: 50Gi } } }
    ---
    apiVersion: v1
    kind: Service
    metadata: { name: postgres, namespace: rag-platform }
    spec:
      selector: { app: postgres }
      ports: [{ port: 5432, targetPort: 5432 }]
    # Prefer a managed Postgres (RDS / Cloud SQL) over this in production —
    # backup/failover/patching is real operational burden.
''')

f("k8s/redis.yaml", '''
    apiVersion: apps/v1
    kind: Deployment
    metadata: { name: redis, namespace: rag-platform }
    spec:
      replicas: 1
      selector: { matchLabels: { app: redis } }
      template:
        metadata: { labels: { app: redis } }
        spec:
          containers: [{ name: redis, image: "redis:7-alpine", ports: [{ containerPort: 6379 }] }]
    ---
    apiVersion: v1
    kind: Service
    metadata: { name: redis, namespace: rag-platform }
    spec:
      selector: { app: redis }
      ports: [{ port: 6379, targetPort: 6379 }]
''')

f("k8s/auth-service.yaml", '''
    apiVersion: apps/v1
    kind: Deployment
    metadata: { name: auth-service, namespace: rag-platform }
    spec:
      replicas: 2
      selector: { matchLabels: { app: auth-service } }
      template:
        metadata: { labels: { app: auth-service } }
        spec:
          containers:
            - name: auth-service
              image: registry.example.com/auth-service:v1.0.0
              envFrom: [{ secretRef: { name: auth-service-secrets } }]
              readinessProbe: { httpGet: { path: /health, port: 8000 } }
              resources: { requests: { cpu: 200m, memory: 256Mi }, limits: { cpu: 500m, memory: 512Mi } }
    ---
    apiVersion: v1
    kind: Service
    metadata: { name: auth-service, namespace: rag-platform }
    spec:
      selector: { app: auth-service }
      ports: [{ port: 80, targetPort: 8000 }]
    ---
    apiVersion: autoscaling/v2
    kind: HorizontalPodAutoscaler
    metadata: { name: auth-service, namespace: rag-platform }
    spec:
      scaleTargetRef: { apiVersion: apps/v1, kind: Deployment, name: auth-service }
      minReplicas: 2
      maxReplicas: 6
      metrics: [{ type: Resource, resource: { name: cpu, target: { type: Utilization, averageUtilization: 70 } } }]
''')

f("k8s/rag-service.yaml", '''
    apiVersion: apps/v1
    kind: Deployment
    metadata: { name: rag-service, namespace: rag-platform }
    spec:
      replicas: 2
      selector: { matchLabels: { app: rag-service } }
      template:
        metadata: { labels: { app: rag-service } }
        spec:
          containers:
            - name: rag-service
              image: registry.example.com/rag-service:v1.0.0  # models baked in at build time
              envFrom: [{ secretRef: { name: rag-service-secrets } }]
              readinessProbe: { httpGet: { path: /health, port: 8000 } }
              resources: { requests: { cpu: "1", memory: 2Gi }, limits: { cpu: "2", memory: 4Gi } }
              # If NOT baking models into the image, mount a pre-populated PVC instead:
              # volumeMounts: [{ name: models, mountPath: /code/models, readOnly: true }]
          # volumes: [{ name: models, persistentVolumeClaim: { claimName: rag-models-pvc, readOnly: true } }]
    ---
    apiVersion: v1
    kind: Service
    metadata: { name: rag-service, namespace: rag-platform }
    spec:
      selector: { app: rag-service }
      ports: [{ port: 80, targetPort: 8000 }]
    ---
    apiVersion: autoscaling/v2
    kind: HorizontalPodAutoscaler
    metadata: { name: rag-service, namespace: rag-platform }
    spec:
      scaleTargetRef: { apiVersion: apps/v1, kind: Deployment, name: rag-service }
      minReplicas: 2
      maxReplicas: 8
      metrics: [{ type: Resource, resource: { name: cpu, target: { type: Utilization, averageUtilization: 70 } } }]
''')

f("k8s/ingress.yaml", '''
    apiVersion: networking.k8s.io/v1
    kind: Ingress
    metadata: { name: rag-platform, namespace: rag-platform }
    spec:
      rules:
        - http:
            paths:
              - path: /api/v1/auth
                pathType: Prefix
                backend: { service: { name: auth-service, port: { number: 80 } } }
              - path: /api/v1/users
                pathType: Prefix
                backend: { service: { name: auth-service, port: { number: 80 } } }
              - path: /.well-known
                pathType: Prefix
                backend: { service: { name: auth-service, port: { number: 80 } } }
              - path: /api/v1/documents
                pathType: Prefix
                backend: { service: { name: rag-service, port: { number: 80 } } }
              # Future: add one more path block for agents-service here.
''')

f("k8s/network-policies.yaml", '''
    apiVersion: networking.k8s.io/v1
    kind: NetworkPolicy
    metadata: { name: deny-all-default, namespace: rag-platform }
    spec:
      podSelector: {}
      policyTypes: [Ingress]
    ---
    apiVersion: networking.k8s.io/v1
    kind: NetworkPolicy
    metadata: { name: allow-ingress-to-services, namespace: rag-platform }
    spec:
      podSelector: { matchExpressions: [{ key: app, operator: In, values: [auth-service, rag-service] }] }
      policyTypes: [Ingress]
      ingress: [{ from: [{ namespaceSelector: {} }] }]  # tighten to the ingress controller's namespace in production
''')


# ===========================================================================
# 5. Root files
# ===========================================================================

f("README.md", '''
    # RAG Platform — Microservices Monorepo

    ```
    packages/platform-auth/   shared JWT verification + RBAC (no private key, no DB)
    services/auth-service/    issues tokens, owns users + refresh_tokens
    services/rag-service/     multimodal ingestion, hybrid retrieval, generation
    k8s/                      Kubernetes manifests for all of the above
    ```

    This script only scaffolds structure + the files that are NEW or
    CHANGED vs. the original monolith. See MIGRATION_CHECKLIST.md for the
    exact list of files to copy over unchanged from your existing
    `ai-platform` monolith repo.

    ## Local setup, per package/service

    No `uv init` needed — pyproject.toml already exists in each one. Just:

    ```bash
    cd packages/platform-auth && uv lock && uv sync
    cd ../../services/auth-service && uv lock && uv sync
    cd ../rag-service && uv lock && uv sync
    ```

    Each service keeps its own `.venv` and `uv.lock` — they are
    independently deployable, so independent dependency resolution is
    correct here (this is NOT set up as a `uv` workspace on purpose).

    ## Database

    One Postgres instance, two schemas, two least-privilege roles:

    ```sql
    CREATE SCHEMA auth;
    CREATE SCHEMA rag;
    CREATE ROLE auth_service_role LOGIN PASSWORD '...';
    GRANT USAGE, CREATE ON SCHEMA auth TO auth_service_role;
    CREATE ROLE rag_service_role LOGIN PASSWORD '...';
    GRANT USAGE, CREATE ON SCHEMA rag TO rag_service_role;
    ```

    Each service's `DATABASE_URL` sets `search_path` to its own schema (see
    each `.env.example`) and keeps its own Alembic migration history.
''')

f(".gitignore", '''
    .venv/
    __pycache__/
    *.pyc
    .env
    secrets/
    *.pem
    .pytest_cache/
    .ruff_cache/
    data/uploads/
    models/
''')


# ===========================================================================
# Write everything
# ===========================================================================

def main() -> None:
    for rel_dir in EMPTY_DIRS_WITH_INIT:
        d = ROOT / rel_dir
        d.mkdir(parents=True, exist_ok=True)
        init_file = d / "__init__.py"
        if not init_file.exists():
            init_file.write_text("")

    for rel_path, content in FILES.items():
        path = ROOT / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

    checklist_lines = [
        "# MIGRATION_CHECKLIST.md",
        "",
        "Files to copy UNCHANGED from your existing `ai-platform` monolith",
        "into this monorepo. A couple need a one-line trim, noted inline.",
        "",
    ]
    for src, dest in COPY_MAP:
        checklist_lines.append(f"- [ ] `ai-platform/{src}`  ->  `{dest}`")
    checklist_path = ROOT / "MIGRATION_CHECKLIST.md"
    checklist_path.write_text("\n".join(checklist_lines) + "\n")

    print(f"Created {len(FILES)} new files, {len(EMPTY_DIRS_WITH_INIT)} package directories.")
    print(f"Wrote MIGRATION_CHECKLIST.md with {len(COPY_MAP)} files to copy from the monolith.")
    print()
    print("Next steps:")
    print("  1. Copy the files listed in MIGRATION_CHECKLIST.md from ai-platform.")
    print("  2. In app/core/security.py (auth-service copy), add the kid header")
    print("     and JWT_KEY_ID to create_access_token() — see chat history.")
    print("  3. Per package/service: uv lock && uv sync   (uv init is NOT needed —")
    print("     pyproject.toml already exists in every one of them)")
    print("  4. Generate the RS256 keypair for auth-service only:")
    print("     openssl genrsa -out services/auth-service/secrets/private_key.pem 2048")
    print("     openssl rsa -in services/auth-service/secrets/private_key.pem \\")
    print("       -pubout -out services/auth-service/secrets/public_key.pem")
    print("  5. Set up Postgres schemas/roles (see README.md) and run each")
    print("     service's own `alembic upgrade head`.")
    print("  6. docker build each service, apply k8s/*.yaml in order:")
    print("     namespace -> postgres/redis -> secrets -> auth-service -> rag-service -> ingress")


if __name__ == "__main__":
    main()
