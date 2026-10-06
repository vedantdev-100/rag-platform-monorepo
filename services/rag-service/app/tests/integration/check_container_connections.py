"""Read-only container check; does not import/start app.main or consume events.

Run inside the RAG image: python -m app.tests.integration.check_container_connections
Append --http once auth-service is healthy to check JWKS too.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

import httpx
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


async def check(with_http: bool) -> None:
    import rag_contracts  # noqa: F401
    import rag_persistence  # noqa: F401
    from app.models.document import Document as ServiceDocument
    from rag_persistence.models.document import Document as SharedDocument

    assert ServiceDocument is SharedDocument, "Service and shared document models differ"
    print("Shared packages and document model identity: OK")
    engine = create_async_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
            for table in ("rag.documents", "rag.chunks", "rag.outbox", "rag.user_lifecycle_state"):
                assert await conn.scalar(text("SELECT to_regclass(:name)"), {"name": table}), f"Missing table: {table}"
            dimension = await conn.scalar(text("""
                SELECT format_type(a.atttypid, a.atttypmod)
                FROM pg_attribute a
                WHERE a.attrelid = 'rag.chunks'::regclass
                  AND a.attname = 'embedding' AND NOT a.attisdropped
            """))
            assert dimension == "vector(768)", f"Unexpected embedding type: {dimension}"
        print("PostgreSQL: OK; four RAG tables present; vector(768) retained")
    finally:
        await engine.dispose()
    for key in ("REDIS_URL", "PLATFORM_AUTH_REDIS_URL"):
        client = Redis.from_url(os.environ[key], socket_connect_timeout=5, socket_timeout=5)
        try:
            assert await client.ping(), f"PING failed for {key}"
            print(f"{key}: PING OK")
        finally:
            await client.aclose()
    if with_http:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(os.environ["PLATFORM_AUTH_JWKS_URL"])
            response.raise_for_status()
            assert response.json().get("keys"), "JWKS contains no keys"
        print("Auth JWKS from RAG container: OK")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--http", action="store_true")
    args = parser.parse_args()
    try:
        asyncio.run(check(args.http))
    except Exception as exc:
        if isinstance(exc, AssertionError):
            print(f"Schema check failed: {exc}", file=sys.stderr)
        else:
            print(
                f"Container check failed ({type(exc).__name__}).",
                file=sys.stderr,
            )
        sys.exit(1)
