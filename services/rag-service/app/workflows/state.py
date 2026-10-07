"""Short transaction boundaries; durable document state fences Redis redelivery."""
from datetime import timedelta
import uuid

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert

from app.core.config import get_settings
from app.db.session import AsyncSessionLocal
from app.events.source_cleanup import enqueue_cleanup, lock_owner
from app.workflows.policy import can_complete, matches
from rag_contracts import IngestionJob
from rag_persistence.models.document import Document
from rag_persistence.models.chunk import Chunk, EMBEDDING_DIM
from rag_persistence.models.outbox import OutboxMessage
from rag_persistence.utils import utcnow

PUBLISH = "ingestion.publish"
DLQ = "ingestion.dead_letter"


class LostLease(Exception):
    pass


def job_for(document):
    return IngestionJob(document.job_id, document.id, document.owner_id,
                        document.generation, document.processing_version)


async def locked_document(session, owner_id, document_id):
    owner = await lock_owner(session, owner_id)
    document = (await session.execute(select(Document).where(Document.id == document_id)
                .with_for_update().execution_options(populate_existing=True))).scalar_one_or_none()
    return owner, document


async def put_message(session, *, kind, key, payload, job=None, available_at=None):
    now = utcnow()
    await session.execute(insert(OutboxMessage).values(
        kind=kind, deduplication_key=key, payload=payload, status="pending",
        aggregate_id=job.document_id if job else None, owner_id=job.owner_id if job else None,
        available_at=available_at or now,
    ).on_conflict_do_update(
        index_elements=[OutboxMessage.deduplication_key],
        set_={"status": "pending", "available_at": available_at or now, "locked_by": None,
              "locked_until": None, "published_at": None, "updated_at": now},
        where=OutboxMessage.status.in_(["published", "failed"]),
    ))


def attempt_key(document):
    return f"ingest:{document.job_id}:{document.generation}:{document.retry_count}"


async def queue_document(session, document, available_at=None):
    job = job_for(document)
    await put_message(session, kind=PUBLISH, key=attempt_key(document), payload=job.as_dict(),
                      job=job, available_at=available_at)


async def terminal_or_retry(session, document, reason, *, retryable):
    settings = get_settings()
    document.retry_count += 1
    document.processing_token = None
    document.processing_lease_until = None
    document.failure_reason = reason
    if retryable and document.retry_count < settings.INGESTION_MAX_ATTEMPTS:
        delay = min(300, settings.INGESTION_RETRY_BASE_SECONDS * (2 ** (document.retry_count - 1)))
        document.status = "pending"
        document.next_retry_at = utcnow() + timedelta(seconds=delay)
        await queue_document(session, document, document.next_retry_at)
    else:
        document.status = "failed"
        document.next_retry_at = None
        job = job_for(document)
        await put_message(session, kind=DLQ, key=f"dlq:{job.job_id}:{job.generation}", job=job,
                          payload={"v": 1, "job": job.as_dict(), "reason": reason,
                                   "failed_attempts": document.retry_count})


async def claim(job):
    settings = get_settings()
    async with AsyncSessionLocal() as session:
        async with session.begin():
            owner, document = await locked_document(session, job.owner_id, job.document_id)
            if owner.is_deleted or not matches(document, job) or document.status != "pending":
                return None
            if not document.doc_metadata.get("source_ready") or not document.source_uri:
                return None
            if document.next_retry_at and document.next_retry_at > utcnow():
                return None
            token = uuid.uuid4()
            document.status = "processing"
            document.processing_token = token
            document.processing_lease_until = utcnow() + timedelta(seconds=settings.INGESTION_LEASE_SECONDS)
            document.next_retry_at = None
            snapshot = {"uri": document.source_uri, "title": document.title,
                        "checksum": document.checksum, "size": document.file_size_bytes}
    return token, snapshot


async def renew(job, token):
    settings = get_settings()
    async with AsyncSessionLocal() as session:
        async with session.begin():
            result = await session.execute(update(Document).where(
                Document.id == job.document_id, Document.owner_id == job.owner_id,
                Document.job_id == job.job_id, Document.generation == job.generation,
                Document.processing_version == job.processing_version, Document.status == "processing",
                Document.processing_token == token, Document.processing_lease_until > utcnow(),
            ).values(processing_lease_until=utcnow() + timedelta(seconds=settings.INGESTION_LEASE_SECONDS)))
    return bool(result.rowcount)


async def complete(job, token, chunk_data, vectors, metadata):
    async with AsyncSessionLocal() as session:
        async with session.begin():
            owner, document = await locked_document(session, job.owner_id, job.document_id)
            if owner.is_deleted or not can_complete(document, job, token, utcnow()):
                raise LostLease()
            # The entire replacement, metadata and success status commit once.
            await session.execute(delete(Chunk).where(Chunk.document_id == document.id))
            session.add_all([Chunk(document_id=document.id, chunk_index=index, modality=chunk.modality,
                                   content=chunk.content, embedding=vector, chunk_metadata=chunk.metadata,
                                   processing_version=job.processing_version)
                             for index, (chunk, vector) in enumerate(zip(chunk_data, vectors, strict=True))])
            document.doc_metadata = {**document.doc_metadata, **metadata, "source_ready": True,
                                     "chunks": len(chunk_data)}
            document.parser_provider = metadata.get("parser_provider") or get_settings().RAG_PARSER_BACKEND
            document.parser_version = metadata.get("parser_version")
            document.status = "ingested"
            document.failure_reason = None
            document.processing_token = None
            document.processing_lease_until = None
            document.next_retry_at = None
            document.processed_at = utcnow()
            document.embedding_model = get_settings().RAG_EMBEDDING_MODEL
            document.embedding_dimension = EMBEDDING_DIM
            settings = get_settings()
            document.embedding_model_revision = (settings.EMBEDDING_SERVICE_REVISION
                if settings.RAG_EMBEDDING_BACKEND == "http" else None)
            document.doc_metadata = {**document.doc_metadata,
                "embedding_backend": settings.RAG_EMBEDDING_BACKEND,
                "embedding_revision": document.embedding_model_revision}


async def fail(job, token, reason, *, retryable):
    async with AsyncSessionLocal() as session:
        async with session.begin():
            owner, document = await locked_document(session, job.owner_id, job.document_id)
            if owner.is_deleted or not can_complete(document, job, token, utcnow()):
                return
            await terminal_or_retry(session, document, reason, retryable=retryable)


async def abort_upload(document_id, owner_id, upload_token, uri, reason, *, not_before=None):
    async with AsyncSessionLocal() as session:
        async with session.begin():
            _owner, document = await locked_document(session, owner_id, document_id)
            if document is None or (document.processing_token == upload_token
                                    and not document.doc_metadata.get("source_ready")):
                await enqueue_cleanup(session, uri, document_id=document_id, owner_id=owner_id,
                                      not_before=not_before)
                if document is not None:
                    document.status = "failed"
                    document.failure_reason = reason
                    document.source_uri = None
                    document.processing_token = None
                    document.processing_lease_until = None


async def reconcile_once(*, document_id=None):
    """Recover interrupted uploads, dead workers, and lost/removed broker entries."""
    now = utcnow()
    async with AsyncSessionLocal() as session:
        # Enumerate candidates without holding row locks; recheck each under
        # owner-then-document locks, in the same order as lifecycle deletion.
        query = select(Document.id, Document.owner_id).where(
            Document.job_id.is_not(None),
            ((Document.status == "pending") &
             ((Document.next_retry_at.is_(None)) | (Document.next_retry_at <= now)) &
             ((Document.doc_metadata["source_ready"].astext == "true") |
              (Document.processing_lease_until <= now))) |
            ((Document.status == "processing") & (Document.processing_lease_until <= now)),
        ).order_by(Document.created_at).limit(100)
        if document_id is not None:
            query = query.where(Document.id == document_id)
        candidates = (await session.execute(query)).all()
    for document_id, owner_id in candidates:
        async with AsyncSessionLocal() as session:
            async with session.begin():
                owner, document = await locked_document(session, owner_id, document_id)
                if document is None or owner.is_deleted or document.job_id is None:
                    continue
                if document.status not in {"pending", "processing"}:
                    continue
                if document.next_retry_at and document.next_retry_at > utcnow():
                    continue
                if not document.doc_metadata.get("source_ready"):
                    if document.processing_lease_until and document.processing_lease_until <= utcnow():
                        uri = document.source_uri
                        document.status = "failed"
                        document.failure_reason = "upload_interrupted"
                        document.source_uri = None
                        document.processing_token = None
                        document.processing_lease_until = None
                        await enqueue_cleanup(session, uri, document_id=document.id, owner_id=owner_id)
                    continue
                if document.status == "processing":
                    if document.processing_lease_until and document.processing_lease_until > utcnow():
                        continue
                    await terminal_or_retry(session, document, "worker_lease_expired", retryable=True)
                    continue
                message = (await session.execute(select(OutboxMessage).where(
                    OutboxMessage.deduplication_key == attempt_key(document)))).scalar_one_or_none()
                if message and message.status == "published" and message.published_at:
                    if message.published_at > utcnow() - timedelta(seconds=60):
                        continue
                await queue_document(session, document, document.next_retry_at)
