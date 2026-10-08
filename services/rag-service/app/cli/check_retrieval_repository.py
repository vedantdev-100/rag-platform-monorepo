"""Live SQL owner/status checks using uncommitted fixtures; always roll back.

No Redis, MinIO or inference calls. Temporary planner settings exercise exact
filter semantics; this is not an HNSW recall/performance benchmark.
"""
import asyncio
import uuid

from sqlalchemy import text

from app.db.session import AsyncSessionLocal, engine
from app.repositories.chunk_repository import ChunkRepository
from rag_persistence.models import Chunk, Document


async def main():
    owner, other = uuid.uuid4(), uuid.uuid4()
    marker = "retrievalprobe" + uuid.uuid4().hex
    vector = [1.] + [0.] * 767
    expected, documents = None, []
    try:
        async with AsyncSessionLocal() as session:
            try:
                await session.execute(text("SET LOCAL statement_timeout = '30s'"))
                # Isolate filtering correctness from approximate-index recall.
                await session.execute(text("SET LOCAL enable_indexscan = off"))
                for status, identity in (("ingested", owner), ("pending", owner),
                                         ("processing", owner), ("failed", owner),
                                         ("ingested", other)):
                    document = Document(id=uuid.uuid4(), owner_id=identity,
                                        title="Temporary retrieval check", source_type="text", status=status)
                    documents.append(document)
                    session.add(document)
                    if status == "ingested" and identity == owner:
                        expected = document.id
                await session.flush()
                session.add_all([Chunk(document_id=document.id, chunk_index=0,
                                       content=marker, embedding=vector,
                                       chunk_metadata={"pages": [1]}) for document in documents])
                await session.flush()
                repo = ChunkRepository(session)
                vector_results = await repo.similarity_search(vector, owner_id=owner, top_k=50)
                keyword_results = await repo.keyword_search(marker, owner_id=owner, top_k=50)
                for results in (vector_results, keyword_results):
                    assert len(results) == 1 and results[0][0].document_id == expected, (
                        "Search returned unfinished/another-owner documents, or omitted the eligible fixture")
                print("Vector and keyword SQL: owner isolation + ingested-only visibility: OK")
            finally:
                await session.rollback()
                print("Temporary fixtures rolled back; no documents/jobs/objects retained")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
