"""Ingestion orchestration owns short database transactions.

Parsing/chunking/embedding run outside database transactions. Final chunks,
metadata and the ingested status commit together. Current synchronous upload
behavior and status vocabulary are preserved until the queue cutover.
"""
import asyncio
import math
import hashlib
import mimetypes
import uuid

from app.exceptions import IngestionError
from app.logging import get_logger
from app.models.chunk import Chunk, EMBEDDING_DIM
from app.models.document import Document
from app.rag.ingestion.base import Chunker, DocumentParser, EmbeddingGenerator, FileStorage
from app.repositories.chunk_repository import ChunkRepository
from app.repositories.document_repository import DocumentRepository

from app.events.source_cleanup import enqueue_cleanup, lock_owner, record_unattached_source
from app.rag.ingestion.storage import object_location
from rag_persistence.utils import utcnow

logger = get_logger(__name__)


class IngestionService:
    def __init__(
        self,
        storage: FileStorage,
        parser: DocumentParser,
        chunker: Chunker,
        embedder: EmbeddingGenerator,
        document_repo: DocumentRepository,
        chunk_repo: ChunkRepository,
    ):
        if document_repo.session is not chunk_repo.session:
            raise ValueError("Ingestion repositories must share the same database session")
        self.storage = storage
        self.parser = parser
        self.chunker = chunker
        self.embedder = embedder
        self.document_repo = document_repo
        self.chunk_repo = chunk_repo
        self.session = document_repo.session

    async def ingest(
        self, *, owner_id: uuid.UUID, filename: str, content: bytes, source_type: str
    ) -> Document:
        
        owner_id = uuid.UUID(str(owner_id))

        if source_type not in self.parser.supported_source_types:
            supported = ", ".join(self.parser.supported_source_types)
            raise IngestionError(f"Unsupported file type for {filename!r}. Supported types: {supported}")

        document_id = uuid.uuid4()
        try:
            uri = await self.storage.save(content, filename)
        except BaseException as exc:
            source_uri = getattr(exc, "source_uri", None)
            if source_uri:
                await record_unattached_source(source_uri, document_id=document_id, owner_id=owner_id)
            raise
        location = object_location(uri)

        # Transaction 1: persist the document before external/CPU work.
        try:
            owner_state = await lock_owner(self.session, owner_id)
            if owner_state.is_deleted:
                raise IngestionError("Owner was deleted; ingestion is not permitted")
            document = await self.document_repo.create(
                Document(
                    id=document_id,
                    owner_id=owner_id,
                    title=filename,
                    source_type=source_type,
                    source_uri=uri,
                    object_bucket=location[0] if location else None,
                    object_key=location[1] if location else None,
                    checksum=hashlib.sha256(content).hexdigest(),
                    file_size_bytes=len(content),
                    mime_type=mimetypes.guess_type(filename)[0] or "application/octet-stream",
                    status="pending",
                )
            )
            await self.document_repo.update_status(document, "processing")
            await self.session.commit()
        except BaseException:
            await self.session.rollback()
            await record_unattached_source(uri, document_id=document_id, owner_id=owner_id)
            raise

        try:
            # No database transaction is held while models are running.
            parsed = await self.parser.parse(content, filename)
            if not parsed.elements:
                raise IngestionError(f"Parsing produced no content for {filename!r}")
            chunk_data = await asyncio.to_thread(self.chunker.chunk, parsed)
            if not chunk_data:
                raise IngestionError(f"Chunking produced no chunks for {filename!r}")

            vectors = await self.embedder.embed([c.content for c in chunk_data])
            if self.embedder.dimensions != EMBEDDING_DIM:
                raise IngestionError("Embedding provider dimension does not match the database schema")
            if len(vectors) != len(chunk_data):
                raise IngestionError("Embedding count does not match chunk count")
            for vector in vectors:
                if len(vector) != EMBEDDING_DIM:
                    raise IngestionError(f"Embedding must contain {EMBEDDING_DIM} values")
                try:
                    finite = all(math.isfinite(value) for value in vector)
                except (TypeError, ValueError, OverflowError) as exc:
                    raise IngestionError("Embedding contains invalid numeric values") from exc
                if not finite:
                    raise IngestionError("Embedding contains non-finite values")

            # Transaction 2: owner and document locks serialize completion
            # against user deletion without holding locks during model work.
            owner_state = await lock_owner(self.session, owner_id)
            if owner_state.is_deleted:
                raise IngestionError("Owner was deleted during ingestion")
            document = await self.document_repo.get_by_id_for_update(document_id)
            if document is None or document.owner_id != owner_id or document.status != "processing":
                raise IngestionError("Document was removed or is no longer eligible for ingestion")

            chunks = [
                Chunk(
                    document_id=document_id,
                    chunk_index=i,
                    modality=cd.modality,
                    content=cd.content,
                    embedding=vector,
                    chunk_metadata=cd.metadata,
                )
                for i, (cd, vector) in enumerate(zip(chunk_data, vectors, strict=True))
            ]
            await self.chunk_repo.bulk_create(chunks)
            await self.document_repo.update_metadata(document, {**parsed.metadata, "chunks": len(chunks)})
            document.processed_at = utcnow()
            document.embedding_dimension = EMBEDDING_DIM
            await self.document_repo.update_status(document, "ingested")
            await self.session.commit()
        except BaseException as exc:
            # Flush failures invalidate the transaction. Roll back before
            # using this session to record failure; reload expired ORM state.
            await self.session.rollback()
            if isinstance(exc, Exception):
                try:
                    failed_document = await self.document_repo.get_by_id_for_update(document_id)
                    if failed_document is None:
                        await enqueue_cleanup(self.session, uri, document_id=document_id, owner_id=owner_id)
                    elif failed_document.status == "processing":
                        # Retain failed sources for inspection and future retry.
                        failed_document.failure_reason = type(exc).__name__
                        await self.document_repo.update_status(failed_document, "failed")
                    await self.session.commit()
                except Exception:
                    await self.session.rollback()
                    logger.exception("document_failure_status_update_failed", document_id=str(document_id))
                logger.exception("document_ingestion_failed", document_id=str(document_id))
            raise

        # Logging occurs after commit, outside failure-state handling.
        logger.info(
            "document_ingested",
            document_id=str(document_id),
            chunk_count=len(chunks),
            parser_metadata=parsed.metadata,
        )
        return document
