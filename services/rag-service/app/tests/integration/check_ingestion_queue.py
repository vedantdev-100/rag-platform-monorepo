"""Actual DB/MinIO/Redis durability probe; injected parser/embedder avoid ML work.

Stop rag-worker first. All rows/objects use one random owner; stream entries
created by the probe are tracked and removed. No real Auth user is touched.
"""
import asyncio
import hashlib
import uuid
from datetime import timedelta

from sqlalchemy import delete, select, update

from app.core.config import get_settings
from app.db.session import AsyncSessionLocal, engine
from app.events.consumer import UserEventConsumer
from app.events.source_cleanup import cleanup_once
from app.rag.ingestion.storage_factory import build_file_storage
from app.workflows.broker import ensure_group, publish_once, redis_client
from app.workflows.execution import process_job
from app.workflows.policy import processing_version
from app.workflows.state import DLQ, PUBLISH, LostLease, claim, complete, job_for, reconcile_once
from app.workflows.submission import submit
from rag_contracts import ChunkData, ParsedDocument, ParsedElement
from rag_persistence.models.chunk import Chunk
from rag_persistence.models.document import Document
from rag_persistence.models.outbox import OutboxMessage
from rag_persistence.models.user_lifecycle_state import UserLifecycleState
from rag_persistence.utils import utcnow


class Parser:
    async def parse(self, content, filename):
        return ParsedDocument(elements=[ParsedElement(content.decode())], metadata={"probe": True})


class Chunker:
    def chunk(self, parsed):
        return [ChunkData(parsed.elements[0].text), ChunkData("Second durable test chunk")]


class Embedder:
    dimensions = 768
    def __init__(self, failure=None): self.failure = failure
    async def embed(self, texts):
        if self.failure == "transient": raise OSError("simulated embedding outage")
        if self.failure == "invalid": return [[0.1] * 767 for _ in texts]
        return [[0.1] * 768 for _ in texts]


class OfflineRedis:
    async def xadd(self, *args, **kwargs):
        raise ConnectionError("simulated Redis outage")


class TrackedRedis:
    def __init__(self, client): self.client, self.entries = client, []
    async def xadd(self, stream, values):
        identity = await self.client.xadd(stream, values)
        self.entries.append((stream, identity))
        return identity


async def main():
    engine.echo = False
    settings, owner_id = get_settings(), uuid.uuid4()
    settings.DEBUG = False  # Suppress expected simulated-failure tracebacks in this probe process only.
    storage, client = build_file_storage(), redis_client()
    tracked, uris = TrackedRedis(client), []
    consumer = UserEventConsumer(settings.REDIS_URL, settings.USER_EVENTS_STREAM, settings.USER_EVENTS_CONSUMER_GROUP)

    async def accept():
        async with AsyncSessionLocal() as session:
            document = await submit(session, storage, owner_id=owner_id, filename="step09-probe.txt",
                                    source_type="txt", content=b"Durable queue test content")
            uris.append(document.source_uri)
            return job_for(document), document.source_uri

    async def row(job):
        async with AsyncSessionLocal() as session:
            return await session.get(Document, job.document_id)

    async def chunks(job):
        async with AsyncSessionLocal() as session:
            return set((await session.execute(select(Chunk.id).where(Chunk.document_id == job.document_id))).scalars())

    async def run(job, failure=None):
        await process_job(job, parser=Parser(), chunker=Chunker(), embedder=Embedder(failure), storage=storage)

    async def due_now(job):
        async with AsyncSessionLocal() as session:
            async with session.begin():
                await session.execute(update(Document).where(Document.id == job.document_id).values(next_retry_at=utcnow()))
                await session.execute(update(OutboxMessage).where(OutboxMessage.aggregate_id == job.document_id,
                                    OutboxMessage.kind == PUBLISH).values(available_at=utcnow()))

    try:
        await ensure_group(client)
        job, uri = await accept()
        assert (await row(job)).status == "pending"
        async with AsyncSessionLocal() as session:
            message_id = await session.scalar(select(OutboxMessage.id).where(
                OutboxMessage.aggregate_id == job.document_id, OutboxMessage.kind == PUBLISH))
        await publish_once(OfflineRedis(), message_id=message_id)
        async with AsyncSessionLocal() as session:
            assert (await session.get(OutboxMessage, message_id)).status == "pending"
        await due_now(job)
        await publish_once(tracked, message_id=message_id)
        async with AsyncSessionLocal() as session:
            assert (await session.get(OutboxMessage, message_id)).status == "published"
        print("Accepted source + job survive broker outage; publication retries: OK")
        await run(job)
        assert (await row(job)).status == "ingested"
        first = await chunks(job)
        assert len(first) == 2
        await run(job)
        assert await chunks(job) == first
        print("Successful ingestion and duplicate delivery produce exactly two chunks: OK")

        retry_job, _ = await accept()
        await run(retry_job, "transient")
        retry_row = await row(retry_job)
        assert retry_row.status == "pending" and retry_row.retry_count == 1
        assert retry_row.next_retry_at and not await chunks(retry_job)
        await due_now(retry_job)
        await run(retry_job)
        assert (await row(retry_job)).status == "ingested"
        print("Transient failure commits durable retry before later success: OK")

        exhausted_job, _ = await accept()
        for _ in range(settings.INGESTION_MAX_ATTEMPTS):
            await due_now(exhausted_job)
            await run(exhausted_job, "transient")
        exhausted = await row(exhausted_job)
        assert exhausted.status == "failed" and exhausted.retry_count == settings.INGESTION_MAX_ATTEMPTS
        assert not await chunks(exhausted_job)
        print("Repeated transient failures stop at the configured attempt limit: OK")

        bad_job, _ = await accept()
        await run(bad_job, "invalid")
        assert (await row(bad_job)).status == "failed" and not await chunks(bad_job)
        async with AsyncSessionLocal() as session:
            dead_id = await session.scalar(select(OutboxMessage.id).where(
                OutboxMessage.aggregate_id == bad_job.document_id, OutboxMessage.kind == DLQ))
        assert dead_id
        await publish_once(tracked, message_id=dead_id)
        print("Invalid embeddings leave zero chunks and a durable dead-letter message: OK")

        lease_job, _ = await accept()
        old_token, _ = await claim(lease_job)
        async with AsyncSessionLocal() as session:
            async with session.begin():
                await session.execute(update(Document).where(Document.id == lease_job.document_id).values(
                    processing_lease_until=utcnow() - timedelta(seconds=1)))
        await reconcile_once(document_id=lease_job.document_id)
        assert (await row(lease_job)).status == "pending"
        await due_now(lease_job)
        new_token, _ = await claim(lease_job)
        try:
            await complete(lease_job, old_token, [ChunkData("stale")], [[0.1] * 768], {})
        except LostLease:
            pass
        else:
            raise AssertionError("Stale processing token committed")
        await complete(lease_job, new_token, [ChunkData("current")], [[0.1] * 768], {})
        assert len(await chunks(lease_job)) == 1
        print("Expired lease is recovered; stale token cannot commit: OK")

        reserved_id = uuid.uuid4()
        reserved_uri = storage.allocate("interrupted.txt", reserved_id, owner_id)
        uris.append(reserved_uri)
        async with AsyncSessionLocal() as session:
            async with session.begin():
                session.add(Document(id=reserved_id, owner_id=owner_id, title="interrupted.txt", source_type="txt",
                    source_uri=reserved_uri, status="pending", job_id=uuid.uuid4(), generation=1,
                    processing_version=processing_version(settings), processing_token=uuid.uuid4(),
                    processing_lease_until=utcnow() - timedelta(seconds=1), doc_metadata={"source_ready": False}))
        await storage.write(reserved_uri, b"interrupted bytes", "interrupted.txt")
        await reconcile_once(document_id=reserved_id)
        async with AsyncSessionLocal() as session:
            document = await session.get(Document, reserved_id)
            assert document.status == "failed" and document.source_uri is None
        assert await cleanup_once(storage, source_uri=reserved_uri)
        print("Interrupted source reservation is failed and cleaned: OK")

        deleted_job, deleted_uri = await accept()
        await consumer._handle({"event": "user.deleted", "user_id": str(owner_id)}, "step09-probe-deleted")
        await run(deleted_job)
        assert await row(deleted_job) is None and not await chunks(deleted_job)
        assert await cleanup_once(storage, source_uri=deleted_uri)
        print("User deletion fences queued jobs and source cleanup remains functional: OK")
    finally:
        await consumer.stop()
        for stream, identity in tracked.entries:
            await client.xdel(stream, identity)
        await client.aclose()
        for uri in uris:
            await storage.delete(uri)
        async with AsyncSessionLocal() as session:
            async with session.begin():
                await session.execute(delete(Document).where(Document.owner_id == owner_id))
                await session.execute(delete(OutboxMessage).where(OutboxMessage.owner_id == owner_id))
                await session.execute(delete(UserLifecycleState).where(UserLifecycleState.user_id == owner_id))
        await engine.dispose()
        print("Disposable probe sources and database rows cleaned.")


if __name__ == '__main__':
    asyncio.run(main())
