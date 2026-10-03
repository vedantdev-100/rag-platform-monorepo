"""
Orchestrates the full ingestion flow: raw upload -> stored file -> parsed
-> chunked -> embedded -> persisted. Depends only on the interfaces in
base.py (constructor injection), so any stage's backend can be swapped
(via app.rag.ingestion.factory, driven by Settings) without this class
changing at all.
"""
import asyncio
import uuid

from app.exceptions import IngestionError
from app.logging import get_logger
from app.models.chunk import Chunk
from app.models.document import Document
from app.rag.ingestion.base import Chunker, DocumentParser, EmbeddingGenerator, FileStorage
from app.repositories.chunk_repository import ChunkRepository
from app.repositories.document_repository import DocumentRepository

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
        self.storage = storage
        self.parser = parser
        self.chunker = chunker
        self.embedder = embedder
        self.document_repo = document_repo
        self.chunk_repo = chunk_repo

    async def ingest(
        self, *, owner_id: uuid.UUID, filename: str, content: bytes, source_type: str
    ) -> Document:
        # Reject unsupported types before anything is written to disk or the
        # database — no orphan file, no "failed" row for a request that was
        # never going to work.
        if source_type not in self.parser.supported_source_types:
            supported = ", ".join(self.parser.supported_source_types)
            raise IngestionError(f"Unsupported file type for {filename!r}. Supported types: {supported}")

        # 1. Persist the raw file first, outside the DB — see storage.py
        # for why blobs never go in a Postgres row.
        uri = await self.storage.save(content, filename)

        document = await self.document_repo.create(
            Document(
                owner_id=owner_id,
                title=filename,
                source_type=source_type,
                source_uri=uri,
                status="pending",
            )
        )

        try:
            document = await self.document_repo.update_status(document, "processing")

            # 2. Parse: raw bytes -> layout-aware ParsedDocument
            parsed = await self.parser.parse(content, filename)
            if not parsed.elements:
                raise IngestionError(f"Parsing produced no content for {filename!r}")

            # 3. Chunk: ParsedDocument -> list[ChunkData], context-aware.
            # Tokenizing is CPU-bound, so keep it off the event loop.
            chunk_data = await asyncio.to_thread(self.chunker.chunk, parsed)
            if not chunk_data:
                raise IngestionError(f"Chunking produced no chunks for {filename!r}")

            # 4. Embed: batch all chunk texts in one call — most embedding
            # backends (including sentence-transformers) are far more
            # efficient batched than called once per chunk. The text embedded
            # is the same text stored (and full-text indexed): headings
            # included.
            vectors = await self.embedder.embed([c.content for c in chunk_data])

            # 5. Persist chunks with their embeddings.
            chunks = [
                Chunk(
                    document_id=document.id,
                    chunk_index=i,
                    modality=cd.modality,
                    content=cd.content,
                    embedding=vector,
                    chunk_metadata=cd.metadata,
                )
                for i, (cd, vector) in enumerate(zip(chunk_data, vectors))
            ]
            await self.chunk_repo.bulk_create(chunks)

            # Record what the parser found so it's visible per document:
            # e.g. pictures > pictures_described means some picture content
            # is NOT searchable (picture description was off or skipped it).
            await self.document_repo.update_metadata(document, {**parsed.metadata, "chunks": len(chunks)})
            document = await self.document_repo.update_status(document, "ingested")
            logger.info(
                "document_ingested", document_id=str(document.id), chunk_count=len(chunks), **parsed.metadata
            )
            return document

        except Exception:
            await self.document_repo.update_status(document, "failed")
            logger.warning("document_ingestion_failed", document_id=str(document.id))
            raise
