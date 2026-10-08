import asyncio

import pytest

from app.rag.generation.document_status import document_events
from app.rag.generation.service import reserve, noop
from app.rag.generation.settings import GenerationSettings
from app.rag.generation.types import GenerationError


@pytest.mark.asyncio
async def test_status_progress_terminal_and_cleanup():
    settings = GenerationSettings(_env_file=None)
    settings.RAG_DOCUMENT_EVENTS_POLL_SECONDS = 0.001
    lease = await reserve(asyncio.Semaphore(1))
    states = iter([{"status": "processing"}, {"status": "ingested"}])

    async def read(*a):
        return next(states)

    events = [
        e
        async for e in document_events(
            "id", "owner", settings, lease, noop, {"status": "pending"}, "req", read
        )
    ]
    assert sum("event: status" in e for e in events) == 3
    assert "event: done" in events[-1] and lease.released


@pytest.mark.asyncio
async def test_deleted_document_ends_stream():
    settings = GenerationSettings(_env_file=None)
    settings.RAG_DOCUMENT_EVENTS_POLL_SECONDS = 0.001
    lease = await reserve(asyncio.Semaphore(1))

    async def read(*a):
        raise GenerationError("document_not_found", 404)

    events = [
        e
        async for e in document_events(
            "id", "owner", settings, lease, noop, {"status": "pending"}, "req", read
        )
    ]
    assert "document_not_found" in events[-1] and lease.released


@pytest.mark.asyncio
async def test_status_expired_stream_and_cancel():
    settings = GenerationSettings(_env_file=None)
    settings.RAG_DOCUMENT_EVENTS_MAX_SECONDS = 0.01
    lease = await reserve(asyncio.Semaphore(1))
    events = [
        e
        async for e in document_events(
            "id", "owner", settings, lease, noop, {"status": "pending"}, "req"
        )
    ]
    assert "stream_ttl" in events[-1] and lease.released
    lease = await reserve(asyncio.Semaphore(1))
    stream = document_events(
        "id", "owner", settings, lease, noop, {"status": "pending"}, "req"
    )
    await anext(stream)
    await stream.aclose()
    assert lease.released


@pytest.mark.asyncio
async def test_snapshot_owner_isolation_and_session_closed(monkeypatch):
    from types import SimpleNamespace
    from uuid import UUID
    from app.rag.generation.document_status import snapshot
    from app.db import session as sessions
    from app.repositories import document_repository

    closed = []

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            closed.append(True)

    class Repo:
        def __init__(self, session):
            pass

        async def get_by_id(self, id):
            return SimpleNamespace(
                owner_id=UUID(int=1),
                id=id,
                status="ingested",
                generation=1,
                retry_count=0,
                processed_at=None,
            )

    monkeypatch.setattr(sessions, "AsyncSessionLocal", Session)
    monkeypatch.setattr(document_repository, "DocumentRepository", Repo)
    with pytest.raises(GenerationError, match="document_not_found"):
        await snapshot(UUID(int=3), str(UUID(int=2)))
    assert closed == [True]
    result = await snapshot(UUID(int=3), str(UUID(int=1)))
    assert result["status"] == "ingested" and len(closed) == 2
