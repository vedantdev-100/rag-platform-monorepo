"""Service configuration and request-session lifecycle remain in rag-service."""
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from rag_persistence.db.session import create_session_factory

settings = get_settings()

engine, AsyncSessionLocal = create_session_factory(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_timeout=settings.DB_POOL_TIMEOUT,
    pool_recycle=settings.DB_POOL_RECYCLE,
)


async def get_db_session() -> AsyncIterator[AsyncSession]:
    """Yield one session per request and close it on exit."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except BaseException:
            await session.rollback()
            raise
        finally:
            await session.close()
