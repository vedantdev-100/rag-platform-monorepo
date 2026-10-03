# app/rag/retrieval/vector_retriever.py
import uuid

from app.core.config import get_settings
from app.rag.retrieval.base import RetrievedChunk, Retriever
from app.repositories.chunk_repository import ChunkRepository

settings = get_settings()


class VectorRetriever(Retriever):
    def __init__(self, chunk_repo: ChunkRepository, embedder):
        self.chunk_repo = chunk_repo
        self.embedder = embedder

    async def retrieve(self, query: str, *, owner_id: str, top_k: int | None = None) -> list[RetrievedChunk]:
        top_k = top_k or settings.RAG_RETRIEVAL_CANDIDATES
        [query_vector] = await self.embedder.embed([query])
        results = await self.chunk_repo.similarity_search(query_vector, owner_id=uuid.UUID(str(owner_id)), top_k=top_k)
        return [
            RetrievedChunk(
                chunk_id=str(chunk.id), document_id=str(chunk.document_id), content=chunk.content,
                score=1 - distance, modality=chunk.modality, metadata=chunk.chunk_metadata,
            )
            for chunk, distance in results
        ]