# app/rag/retrieval/hybrid_retriever.py
from app.rag.retrieval.base import RetrievedChunk, Retriever, reciprocal_rank_fusion


class HybridRetriever(Retriever):
    def __init__(self, vector_retriever: Retriever, keyword_retriever: Retriever, rrf_k: int = 60):
        self.vector_retriever = vector_retriever
        self.keyword_retriever = keyword_retriever
        self.rrf_k = rrf_k

    async def retrieve(self, query: str, *, owner_id: str, top_k: int | None = None) -> list[RetrievedChunk]:
        vector_results, keyword_results = await asyncio.gather(
            self.vector_retriever.retrieve(query, owner_id=owner_id, top_k=top_k),
            self.keyword_retriever.retrieve(query, owner_id=owner_id, top_k=top_k),
        )
        fused = reciprocal_rank_fusion([vector_results, keyword_results], k=self.rrf_k)
        return fused[:top_k] if top_k else fused


import asyncio  # noqa: E402 (kept at bottom to keep the class definition readable above)