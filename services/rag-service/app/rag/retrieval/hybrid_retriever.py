# app/rag/retrieval/hybrid_retriever.py
from app.rag.retrieval.base import RetrievedChunk, Retriever, reciprocal_rank_fusion


class HybridRetriever(Retriever):
    def __init__(self, vector_retriever: Retriever, keyword_retriever: Retriever, rrf_k: int = 60):
        self.vector_retriever = vector_retriever
        self.keyword_retriever = keyword_retriever
        self.rrf_k = rrf_k

    async def retrieve(self, query: str, *, owner_id: str, top_k: int | None = None) -> list[RetrievedChunk]:
        # Await query embedding before the first DB read. Both retrievers
        # share one AsyncSession, so execute their SQL reads sequentially.
        vector_results = await self.vector_retriever.retrieve(query, owner_id=owner_id, top_k=top_k)
        keyword_results = await self.keyword_retriever.retrieve(query, owner_id=owner_id, top_k=top_k)
        fused = reciprocal_rank_fusion([vector_results, keyword_results], k=self.rrf_k)
        return fused[:top_k] if top_k else fused
