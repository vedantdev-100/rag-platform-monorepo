"""
Retrieval-layer interfaces. Concrete implementations (VectorRetriever using
ChunkRepository, a future BM25-only retriever, a future reranker calling a
cross-encoder model) all implement these — so swapping the retrieval
strategy, the reranking model, or even the vector store backend later is a
new class, not a rewrite of anything that calls into this layer.

Everything here reads its parameters from Settings by default (top_k, the
hybrid vector/keyword weight, distance metric) rather than hardcoding them,
per the "make everything dynamic" requirement — callers can still override
per-call when a specific request needs to.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class RetrievedChunk:
    """Backend-agnostic result shape — callers (generation, reranking,
    evaluation) depend on this, never on a specific repository's row type."""
    chunk_id: str
    document_id: str
    content: str
    score: float  # higher = more relevant, regardless of the underlying metric
    modality: str = "text"
    metadata: dict[str, Any] = field(default_factory=dict)


class Retriever(ABC):
    """One retrieval strategy: pure vector, pure keyword, or hybrid."""

    @abstractmethod
    async def retrieve(self, query: str, *, owner_id: str, top_k: int | None = None) -> list[RetrievedChunk]:
        ...


class Reranker(ABC):
    """
    Post-retrieval reordering — typically a cross-encoder scoring
    (query, chunk) pairs more precisely than the initial retrieval metric,
    at the cost of being too slow to run over the whole corpus. Takes
    already-retrieved candidates, returns them reordered (and optionally
    trimmed to a smaller top_n).
    """

    @abstractmethod
    async def rerank(self, query: str, chunks: list[RetrievedChunk], *, top_n: int | None = None) -> list[RetrievedChunk]:
        ...


def reciprocal_rank_fusion(
    ranked_lists: list[list[RetrievedChunk]], *, k: int = 60
) -> list[RetrievedChunk]:
    """
    Merges multiple independently-ranked result lists (e.g. vector search
    results + keyword search results) into one ranking, using each item's
    *rank position* rather than its raw score — necessary because cosine
    distance and full-text rank live on incomparable scales. This is what
    HybridRetriever uses to combine vector + keyword results; exposed as a
    standalone function so a future third signal (e.g. a business-logic
    boost, or reranker scores) can be fused in the same way without
    duplicating this logic.
    """
    fused_scores: dict[str, float] = {}
    chunk_by_id: dict[str, RetrievedChunk] = {}
    for ranked_list in ranked_lists:
        for rank, chunk in enumerate(ranked_list):
            fused_scores[chunk.chunk_id] = fused_scores.get(chunk.chunk_id, 0.0) + 1.0 / (k + rank + 1)
            chunk_by_id[chunk.chunk_id] = chunk

    ordered_ids = sorted(fused_scores, key=lambda cid: fused_scores[cid], reverse=True)
    return [
        RetrievedChunk(**{**chunk_by_id[cid].__dict__, "score": fused_scores[cid]})
        for cid in ordered_ids
    ]
