"""Run with: uv run python -m app.tests.integration.check_ingestion_transactions.

Uses the configured PostgreSQL database and writes synthetic, randomly owned
documents. No model inference or real file upload is used. Test rows are
removed in finally. Real database transactions verify rollback behavior.
"""
import asyncio
import uuid

from sqlalchemy import func, select, text

from app.db.session import AsyncSessionLocal
from app.models.chunk import Chunk, EMBEDDING_DIM
from app.models.document import Document
from app.rag.ingestion.base import ChunkData, ParsedDocument, ParsedElement
from app.rag.ingestion.pipeline import IngestionService
from app.repositories.chunk_repository import ChunkRepository
from app.repositories.document_repository import DocumentRepository


class MemoryStorage:
    async def save(self, content, filename):
        return f"memory://transaction-check/{uuid.uuid4()}/{filename}"


class Parser:
    supported_source_types = ("pdf",)

    def __init__(self, session):
        self.session = session

    async def parse(self, content, filename):
        assert not self.session.in_transaction(), "Parsing holds a DB transaction"
        return ParsedDocument(elements=[ParsedElement(text="transaction check")], metadata={"pages": 1})


class Chunker:
    def chunk(self, document):
        return [ChunkData(content="transaction check", metadata={"page": 1})]


class Embedder:
    dimensions = EMBEDDING_DIM

    def __init__(self, mode):
        self.mode = mode

    async def embed(self, texts):
        if self.mode == "short-response":
            return []
        vector = [0.0] * EMBEDDING_DIM
        vector[0] = float("nan") if self.mode == "non-finite" else 1.0
        return [vector]


class DatabaseFailureRepository(DocumentRepository):
    async def update_metadata(self, document, metadata):
        # PostgreSQL aborts this transaction AFTER the chunk insert was flushed.
        await self.session.execute(text("SELECT 1 / 0"))
        raise AssertionError("Expected PostgreSQL division-by-zero error")


async def check_case(mode):
    owner_id = uuid.uuid4()
    try:
        async with AsyncSessionLocal() as session:
            repo_type = DatabaseFailureRepository if mode == "database-failure" else DocumentRepository
            service = IngestionService(
                storage=MemoryStorage(), parser=Parser(session), chunker=Chunker(),
                embedder=Embedder(mode), document_repo=repo_type(session),
                chunk_repo=ChunkRepository(session),
            )
            error = None
            try:
                await service.ingest(
                    owner_id=owner_id, filename="transaction-check.pdf",
                    content=b"synthetic", source_type="pdf",
                )
            except Exception as exc:
                error = exc
            if mode == "success":
                assert error is None, f"Unexpected ingestion failure: {error!r}"
            else:
                assert error is not None, f"Expected failure for {mode}"

        # A DIFFERENT session proves writes were committed or rolled back.
        async with AsyncSessionLocal() as verification:
            document = (await verification.execute(
                select(Document).where(Document.owner_id == owner_id)
            )).scalar_one()
            count = (await verification.execute(
                select(func.count()).select_from(Chunk).where(Chunk.document_id == document.id)
            )).scalar_one()
            expected_status, expected_count = ("ingested", 1) if mode == "success" else ("failed", 0)
            assert document.status == expected_status, (mode, document.status)
            assert count == expected_count, (mode, count)
            if mode == "success":
                assert document.doc_metadata["chunks"] == 1
                assert document.doc_metadata["pages"] == 1
            print(f"PASS {mode}: status={document.status}, committed chunks={count}")
    finally:
        async with AsyncSessionLocal() as cleanup:
            async with cleanup.begin():
                await DocumentRepository(cleanup).delete_all_for_owner(owner_id)


async def main():
    for mode in ("success", "database-failure", "short-response", "non-finite"):
        await check_case(mode)
    print("Transaction checks passed; synthetic database rows removed.")


if __name__ == "__main__":
    asyncio.run(main())
