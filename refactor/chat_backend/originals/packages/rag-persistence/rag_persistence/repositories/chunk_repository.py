"""Write methods flush; the calling service owns the transaction."""
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from rag_persistence.models.chunk import Chunk



class ChunkRepository:
    def __init__(self, session: AsyncSession, *, default_top_k: int):
        self.session = session
        self.default_top_k = default_top_k

    async def bulk_create(self, chunks: list[Chunk]) -> list[Chunk]:
        self.session.add_all(chunks)
        await self.session.flush()
        return chunks

    async def get_by_document(self, document_id: uuid.UUID) -> list[Chunk]:
        result = await self.session.execute(
            select(Chunk).where(Chunk.document_id == document_id).order_by(Chunk.chunk_index)
        )
        return list(result.scalars().all())

    async def similarity_search(
        self, query_embedding: list[float], *, owner_id: uuid.UUID, top_k: int | None = None
    ) -> list[tuple[Chunk, float]]:
        """
        Dense/vector search: cosine-distance nearest-neighbor, scoped to one
        owner's documents. Returns (chunk, distance) pairs — smaller
        distance = more similar. `top_k` defaults from settings
        (RAG_DEFAULT_TOP_K) rather than a hardcoded literal, so it's tunable
        per-environment without a code change; callers needing a specific
        value (e.g. a reranker that wants a wider initial candidate set)
        can still override it per-call.
        """
        from rag_persistence.models.document import Document

        effective_top_k = top_k if top_k is not None else self.default_top_k
        distance = Chunk.embedding.cosine_distance(query_embedding).label("distance")
        stmt = (
            select(Chunk, distance)
            .join(Document, Chunk.document_id == Document.id)
            .where(Document.owner_id == owner_id, Document.status == "ingested")
            .order_by(distance)
            .limit(effective_top_k)
        )
        result = await self.session.execute(stmt)
        return [(row[0], row[1]) for row in result.all()]

    async def keyword_search(
        self, query_text: str, *, owner_id: uuid.UUID, top_k: int | None = None
    ) -> list[tuple[Chunk, float]]:
        """
        Sparse/keyword search: full-text search against `content_tsv`
        (Postgres GENERATED column, GIN-indexed — see the hybrid-search
        migration). Returns (chunk, rank) pairs — higher rank = more
        relevant, using Postgres's ts_rank. This is the other half of
        hybrid search; combined with similarity_search() via reciprocal
        rank fusion in the retrieval layer (app/rag/retrieval/base.py),
        not here — this repository stays a thin DB-access layer.
        """
        from rag_persistence.models.document import Document

        effective_top_k = top_k if top_k is not None else self.default_top_k
        tsquery = func.plainto_tsquery("english", query_text)
        rank = func.ts_rank(Chunk.content_tsv, tsquery).label("rank")
        stmt = (
            select(Chunk, rank)
            .join(Document, Chunk.document_id == Document.id)
            .where(Document.owner_id == owner_id, Document.status == "ingested",
                   Chunk.content_tsv.op("@@")(tsquery))
            .order_by(rank.desc(), Chunk.id)
            .limit(effective_top_k)
        )
        result = await self.session.execute(stmt)
        return [(row[0], row[1]) for row in result.all()]
