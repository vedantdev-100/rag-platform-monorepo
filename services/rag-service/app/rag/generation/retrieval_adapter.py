class SqlEvidenceRetriever:
    async def retrieve(self, query, *, owner_id, top_k):
        from app.db.session import AsyncSessionLocal
        from app.repositories.chunk_repository import ChunkRepository
        from app.rag.retrieval.factory import get_retrieval_service

        async with AsyncSessionLocal() as session:
            result = await get_retrieval_service(ChunkRepository(session)).retrieve(
                session, query, owner_id=owner_id, top_k=top_k
            )
            return result.results
