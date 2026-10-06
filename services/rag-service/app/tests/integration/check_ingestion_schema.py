"""Read-only database preflight/data-preservation check for Step 5.

Run --before while the API is stopped, migrate, then run --after. The snapshot
contains counts, hashes and index definitions, never document/vector contents.
"""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path

from sqlalchemy import text

from app.db.session import AsyncSessionLocal

OLD_COLUMNS = {
    "documents": ["id", "owner_id", "title", "source_type", "source_uri", "status", "doc_metadata", "created_at", "updated_at"],
    "chunks": ["id", "document_id", "chunk_index", "modality", "content", "embedding", "content_tsv", "chunk_metadata", "created_at"],
}


async def fingerprint(session, table, columns):
    # Identifiers come only from OLD_COLUMNS, not from user input/snapshot.
    selected = ", ".join(f'"{name}"' for name in columns)
    result = await session.stream(text(
        f'SELECT to_jsonb(t)::text FROM (SELECT {selected} FROM rag."{table}") AS t ORDER BY t.id'
    ))
    digest = hashlib.sha256()
    count = 0
    async for row in result:
        digest.update(row[0].encode("utf-8"))
        digest.update(b"\n")
        count += 1
    await result.close()
    return {"count": count, "sha256": digest.hexdigest()}


async def capture(session):
    state = {"database": (await session.execute(text("SELECT current_database()"))).scalar_one()}
    for table, columns in OLD_COLUMNS.items():
        state[table] = await fingerprint(session, table, columns)
    statuses = await session.execute(text("SELECT status, COUNT(*) FROM rag.documents GROUP BY status ORDER BY status"))
    state["statuses"] = {row[0]: row[1] for row in statuses}
    indexes = await session.execute(text(
        "SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = 'rag' "
        "AND tablename IN ('documents', 'chunks') ORDER BY indexname"
    ))
    state["indexes"] = {row[0]: row[1] for row in indexes}
    return state


async def main(args):
    async with AsyncSessionLocal() as session:
        revision = (await session.execute(text("SELECT version_num FROM rag.alembic_version"))).scalar_one()
        expected = "ede8cc507e7c" if args.before else "a6f31c9e204b"
        if revision != expected:
            raise RuntimeError(f"Expected database revision {expected}, found {revision}")
        invalid_dimensions = (await session.execute(text(
            "SELECT COUNT(*) FROM rag.chunks WHERE vector_dims(embedding) <> 768"
        ))).scalar_one()
        if invalid_dimensions:
            raise RuntimeError("Unexpected existing vector dimensions; stop and review the database")

        if args.before:
            duplicates = (await session.execute(text(
                "SELECT document_id, chunk_index, COUNT(*) AS count FROM rag.chunks "
                "GROUP BY document_id, chunk_index HAVING COUNT(*) > 1 LIMIT 5"
            ))).all()
            if duplicates:
                raise RuntimeError(f"Duplicate legacy chunk positions found: {duplicates!r}; review before migration")
            state = await capture(session)
            args.snapshot.parent.mkdir(parents=True, exist_ok=True)
            with args.snapshot.open("x", encoding="utf-8") as output:
                json.dump(state, output, indent=2)
            print(f"PASS preflight: documents={state['documents']['count']}, chunks={state['chunks']['count']}")
            print(f"Baseline saved to {args.snapshot}; do not overwrite it before --after")
            return

        before = json.loads(args.snapshot.read_text(encoding="utf-8"))
        after = await capture(session)
        for key in ("database", "documents", "chunks", "statuses"):
            if before[key] != after[key]:
                raise RuntimeError(f"Existing data changed: {key}. Keep the API stopped and review.")
        for name, definition in before["indexes"].items():
            if after["indexes"].get(name) != definition:
                raise RuntimeError(f"Existing index changed or disappeared: {name}")
        for table in ("documents", "chunks"):
            invalid = (await session.execute(text(
                f"SELECT COUNT(*) FROM rag.{table} WHERE processing_version <> 'legacy'"
            ))).scalar_one()
            if invalid:
                raise RuntimeError(f"Unexpected processing-version backfill in {table}")
        for table in ("outbox", "user_lifecycle_state"):
            count = (await session.execute(text(f"SELECT COUNT(*) FROM rag.{table}"))).scalar_one()
            if count:
                raise RuntimeError(f"Expected empty new table {table}; stop and review")
        new_document_defaults = (await session.execute(text(
            "SELECT COUNT(*) FROM rag.documents WHERE retry_count <> 0 OR generation <> 0 "
            "OR object_bucket IS NOT NULL OR object_key IS NOT NULL "
            "OR embedding_model IS NOT NULL OR embedding_model_revision IS NOT NULL"
        ))).scalar_one()
        if new_document_defaults:
            raise RuntimeError("Unexpected workflow/provenance backfill")
        from rag_persistence.db.base import Base
        from rag_persistence.models import Chunk, Document, OutboxMessage, UserLifecycleState  # noqa: F401
        from sqlalchemy.orm import configure_mappers
        configure_mappers()
        if set(Base.metadata.tables) != {"rag.documents", "rag.chunks", "rag.outbox", "rag.user_lifecycle_state"}:
            raise RuntimeError("Unexpected shared ORM table registration")
        print("PASS migration: existing row contents, counts, statuses and indexes preserved")
        print("PASS new columns/defaults, empty workflow tables and shared ORM registration")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--before", action="store_true")
    mode.add_argument("--after", action="store_true")
    parser.add_argument("--snapshot", type=Path, default=Path("step05_schema_baseline.json"))
    asyncio.run(main(parser.parse_args()))
