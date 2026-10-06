"""Model work outside DB transactions; lease-guarded commit after validation."""
import asyncio
import hashlib

from app.core.config import get_settings
from app.exceptions import IngestionError
from app.logging import get_logger
from app.rag.ingestion.storage_factory import build_file_storage
from app.workflows.policy import processing_version, validate_vectors
from app.workflows.state import LostLease, claim, complete, fail, reconcile_once, renew

logger = get_logger(__name__)


class PermanentFailure(Exception):
    pass


async def heartbeat(job, token):
    while True:
        await asyncio.sleep(get_settings().INGESTION_HEARTBEAT_SECONDS)
        if not await renew(job, token):
            raise LostLease()


async def model_work(snapshot, *, parser=None, chunker=None, embedder=None, storage=None):
    if storage is None:
        storage = build_file_storage()
    content = await storage.read(snapshot["uri"])
    if len(content) != snapshot["size"] or hashlib.sha256(content).hexdigest() != snapshot["checksum"]:
        raise PermanentFailure("source_checksum_mismatch")
    if parser is None or chunker is None or embedder is None:
        from app.rag.ingestion.factory import get_document_parser, get_chunker, get_embedding_generator
        # Constructors can load models/tokenizers: keep that work off the
        # event loop so lifecycle, publication and heartbeats still run.
        parser = parser or await asyncio.to_thread(get_document_parser)
        chunker = chunker or await asyncio.to_thread(get_chunker)
        embedder = embedder or await asyncio.to_thread(get_embedding_generator)
    parsed = await parser.parse(content, snapshot["title"])
    if not parsed.elements:
        raise PermanentFailure("parser_produced_no_content")
    chunks = await asyncio.to_thread(chunker.chunk, parsed)
    if not chunks:
        raise PermanentFailure("chunker_produced_no_content")
    vectors = await embedder.embed([chunk.content for chunk in chunks])
    try:
        validate_vectors(vectors, len(chunks), embedder.dimensions)
    except ValueError as exc:
        raise PermanentFailure("invalid_embeddings") from exc
    return chunks, vectors, parsed.metadata


async def process_job(job, *, parser=None, chunker=None, embedder=None, storage=None):
    settings = get_settings()
    claimed = await claim(job)
    if claimed is None:
        return  # Missing/deleted/stale/terminal/busy jobs are fenced in DB.
    token, snapshot = claimed
    work = None
    pulse = None
    try:
        if job.processing_version != processing_version(settings):
            raise PermanentFailure("processing_configuration_changed")
        work = asyncio.create_task(asyncio.wait_for(
            model_work(snapshot, parser=parser, chunker=chunker, embedder=embedder, storage=storage),
            timeout=settings.INGESTION_JOB_TIMEOUT_SECONDS,
        ))
        pulse = asyncio.create_task(heartbeat(job, token))
        done, _ = await asyncio.wait({work, pulse}, return_when=asyncio.FIRST_COMPLETED)
        if pulse in done:
            await pulse  # Raise heartbeat DB errors / lease loss; no stale commit.
            raise LostLease()
        chunks, vectors, metadata = await work
        await complete(job, token, chunks, vectors, metadata)
        logger.info("queued_document_ingested", document_id=str(job.document_id), chunk_count=len(chunks))
    except asyncio.CancelledError:
        # Leave the durable processing lease; reconciliation will retry it.
        raise
    except LostLease:
        raise
    except Exception as exc:
        permanent = isinstance(exc, (PermanentFailure, IngestionError))
        reason = str(exc) if isinstance(exc, PermanentFailure) else type(exc).__name__
        await fail(job, token, reason, retryable=not permanent)
        if settings.DEBUG:
            logger.exception("queued_ingestion_attempt_failed", document_id=str(job.document_id), reason=reason)
        else:
            logger.warning("queued_ingestion_attempt_failed", document_id=str(job.document_id), reason=reason)
    finally:
        tasks = [task for task in (work, pulse) if task is not None]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def reconciliation_loop():
    while True:
        try:
            await reconcile_once()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("ingestion_reconciliation_error", error_type=type(exc).__name__)
        await asyncio.sleep(10)
