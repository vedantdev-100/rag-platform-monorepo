import warnings

# Suppress Pydantic protected namespace UserWarnings from third-party libraries
warnings.filterwarnings(
    "ignore",
    category=UserWarning,
    message=".*conflict with protected namespace.*",
)


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

import asyncio
from app.events.consumer import UserEventConsumer

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
    # exception types) come from platform_auth � no local auth code here.
    setup_auth(app)

# Redis streams for user lifecycle events (user.deleted, user.deactivated, etc.) consumed by rag-service to clean up orphaned documents/chunks.
    consumer = UserEventConsumer(settings.REDIS_URL, settings.USER_EVENTS_STREAM, settings.USER_EVENTS_CONSUMER_GROUP)

    @app.on_event("startup")
    async def _start_consumer():
        app.state.consumer_task = asyncio.create_task(consumer.run())

    @app.on_event("shutdown")
    async def _stop_consumer():
        await consumer.stop()
        app.state.consumer_task.cancel()
        
    # rag-service's OWN exceptions: IngestionError, ModelNotFoundError, etc.
    register_exception_handlers(app, is_production=settings.is_production)

    app.include_router(api_router, prefix=settings.API_V1_PREFIX)

    @app.get("/health")
    async def health_check():
        return {"status": "ok", "environment": settings.ENVIRONMENT}

    # quick check to see what routes are registered
    for route in app.routes:
        print(route.path)

    return app


app = create_app()
