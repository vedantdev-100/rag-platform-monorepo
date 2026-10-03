# app/rag/retrieval/keyword_retriever.py
import uuid

from app.core.config import get_settings
from app.rag.retrieval.base import RetrievedChunk, Retriever
from app.repositories.chunk_repository import ChunkRepository

settings = get_settings()


class KeywordRetriever(Retriever):
    def __init__(self, chunk_repo: ChunkRepository):
        self.chunk_repo = chunk_repo

    async def retrieve(self, query: str, *, owner_id: str, top_k: int | None = None) -> list[RetrievedChunk]:
        top_k = top_k or settings.RAG_RETRIEVAL_CANDIDATES
        results = await self.chunk_repo.keyword_search(query, owner_id=uuid.UUID(str(owner_id)), top_k=top_k)
        return [
            RetrievedChunk(
                chunk_id=str(chunk.id), document_id=str(chunk.document_id), content=chunk.content,
                score=float(rank), modality=chunk.modality, metadata=chunk.chunk_metadata,
            )
            for chunk, rank in results
        ]