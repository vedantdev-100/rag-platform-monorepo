"""
Local cross-encoder reranker (default: BAAI/bge-reranker-base), loaded from
a local MODELS_DIR folder — same pattern as SentenceTransformersEmbedder.
A cross-encoder scores (query, chunk) pairs jointly, which is more accurate
than the cosine-distance/RRF score used to produce the initial candidates,
but too slow to run over an entire corpus — hence: retrieve a wider
candidate set first (RAG_RETRIEVAL_CANDIDATES), rerank only those.
"""
import asyncio

from app.rag.retrieval.base import Reranker, RetrievedChunk


class CrossEncoderReranker(Reranker):
    def __init__(self, model_path: str, device: str | None = None):
        from sentence_transformers import CrossEncoder

        self._model = CrossEncoder(str(model_path), device=device or None)

    async def rerank(
        self, query: str, chunks: list[RetrievedChunk], *, top_n: int | None = None
    ) -> list[RetrievedChunk]:
        if not chunks:
            return []
        pairs = [(query, chunk.content) for chunk in chunks]
        scores = await asyncio.to_thread(self._model.predict, pairs)

        rescored = [
            RetrievedChunk(**{**chunk.__dict__, "score": float(score)})
            for chunk, score in zip(chunks, scores)
        ]
        rescored.sort(key=lambda c: c.score, reverse=True)
        return rescored[:top_n] if top_n else rescored