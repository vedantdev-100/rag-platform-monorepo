"""Service adapter supplies the configured retrieval default."""
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from rag_persistence.repositories.chunk_repository import ChunkRepository as SharedChunkRepository


class ChunkRepository(SharedChunkRepository):
    def __init__(self, session: AsyncSession, *, document_ids=None):
        super().__init__(session, default_top_k=get_settings().RAG_DEFAULT_TOP_K, document_ids=document_ids)
