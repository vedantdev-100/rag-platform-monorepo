"""Live embedding -> retrieval -> optional reranking probe, without DB writes."""
import argparse
import asyncio
from time import perf_counter
import uuid

from sqlalchemy import select, text

from app.db.session import AsyncSessionLocal, engine
from app.rag.retrieval.factory import get_retrieval_service
from app.repositories.chunk_repository import ChunkRepository
from rag_persistence.models import Document


async def main(args):
    try:
        async with AsyncSessionLocal() as session:
            service = get_retrieval_service(ChunkRepository(session))
            started = perf_counter()
            outcome = await service.retrieve(session, args.query, owner_id=str(args.owner_id), top_k=args.top_k)
            elapsed = 1000 * (perf_counter() - started)
            assert len(outcome.results) <= args.top_k
            assert not session.in_transaction(), "Retrieval left a transaction open"
            ids = {uuid.UUID(result.document_id) for result in outcome.results}
            if ids:
                rows = (await session.execute(select(Document.id, Document.owner_id, Document.status)
                                               .where(Document.id.in_(ids)))).all()
                assert len(rows) == len(ids), "A returned document no longer exists"
                assert all(owner == args.owner_id and status == "ingested" for _, owner, status in rows)
            if args.expected_document_id:
                assert args.expected_document_id in ids, "Expected document not in the returned results"
            print(f"Retrieval: backend={outcome.retriever_backend}, reranked={outcome.reranked}, "
                  f"results={len(outcome.results)}, elapsed_ms={elapsed:.1f}")
            print("Returned document IDs:", ", ".join(map(str, sorted(ids))) or "none")
            # A genuinely unused identity must have no results, even for the same query.
            await session.rollback()
            empty = await service.retrieve(session, args.query, owner_id=str(uuid.uuid4()), top_k=args.top_k)
            assert not empty.results, "Empty identity returned another user's chunks"
            version = await session.scalar(text("SELECT extversion FROM pg_extension WHERE extname='vector'"))
            print("Unused-owner isolation: OK; pgvector extension version:", version)
            await session.rollback()
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--owner-id", required=True, type=uuid.UUID)
    parser.add_argument("--query", required=True)
    parser.add_argument("--expected-document-id", type=uuid.UUID)
    parser.add_argument("--top-k", type=int, default=5, choices=range(1, 51))
    asyncio.run(main(parser.parse_args()))
