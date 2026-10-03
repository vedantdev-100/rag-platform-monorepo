"""
Async SQLAlchemy engine + session factory.

Decision: async everywhere. RAG/agent workloads are I/O bound (vector DB
calls, LLM API calls, tool calls); an async stack from the DB layer up
avoids event-loop-blocking sync calls creeping in later.
"""
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings

settings = get_settings()

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    pool_pre_ping=True,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_timeout=settings.DB_POOL_TIMEOUT,
    pool_recycle=settings.DB_POOL_RECYCLE,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db_session() -> AsyncSession:
    """FastAPI dependency — yields one session per request, always closed."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
