"""Register all RAG models against one shared metadata for Alembic."""
from rag_persistence.models.document import Document
from rag_persistence.models.chunk import Chunk
from rag_persistence.models.outbox import OutboxMessage
from rag_persistence.models.user_lifecycle_state import UserLifecycleState

__all__ = ["Document", "Chunk", "OutboxMessage", "UserLifecycleState"]
