"""Bounded retrieval shared by search and future generation orchestration.

Use a fresh, dedicated read-only session. Materialize result DTOs, release its
transaction, then call the optional remote reranker. Never attach pending writes.
"""
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.rag.retrieval.base import RetrievedChunk, Retriever, Reranker
from app.rag.retrieval.validation import normalize_query

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


@dataclass
class RetrievalOutcome:
    query: str
    results: list[RetrievedChunk]
    retriever_backend: str
    reranked: bool


class RetrievalService:
    def __init__(self, retriever: Retriever, reranker: Reranker | None, *,
                 backend: str, default_top_k: int, candidates: int):
        if not 1 <= default_top_k <= 50 or not 1 <= candidates <= 100:
            raise ValueError("Invalid retrieval result/candidate limits")
        self.retriever, self.reranker = retriever, reranker
        self.backend, self.default_top_k, self.candidates = backend, default_top_k, candidates

    async def retrieve(self, session: "AsyncSession", query: str, *,
                       owner_id: str, top_k: int | None = None) -> RetrievalOutcome:
        query = normalize_query(query)
        final_k = self.default_top_k if top_k is None else top_k
        if isinstance(final_k, bool) or not isinstance(final_k, int) or not 1 <= final_k <= 50:
            raise ValueError("top_k must be an integer between 1 and 50")
        if session.in_transaction():
            raise RuntimeError("Retrieval requires a fresh dedicated read-only session")
        # Hybrid needs a broader pool even with reranking disabled. Pure searches
        # need a broader pool only when a reranker is configured.
        candidate_count = max(final_k, self.candidates) if (
            self.backend == "hybrid" or self.reranker is not None) else final_k
        try:
            results = await self.retriever.retrieve(query, owner_id=owner_id, top_k=candidate_count)
        finally:
            # Readers have copied ORM data into RetrievedChunk before this point.
            # Rollback closes the read transaction and returns its connection.
            if session.in_transaction():
                await session.rollback()
        reranked = self.reranker is not None and bool(results)
        if reranked:
            results = await self.reranker.rerank(query, results, top_n=final_k)
        return RetrievalOutcome(query, results[:final_k], self.backend, reranked)
