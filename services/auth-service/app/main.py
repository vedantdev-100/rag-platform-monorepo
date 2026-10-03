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

# mountuing the well_known route separately to avoid circular import issues with platform_auth
from app.api.v1.endpoints import well_known 

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
    app.include_router(well_known.router)

    @app.get("/health")
    async def health_check():
        return {"status": "ok", "environment": settings.ENVIRONMENT}

    # quick check to see what routes are registered
    for route in app.routes:
        print(route.path)

    return app


app = create_app()
