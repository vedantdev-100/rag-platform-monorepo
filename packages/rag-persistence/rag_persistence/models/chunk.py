"""
A Chunk is the unit retrieval actually operates on: a slice of a Document's
content plus its embedding vector. `embedding` is fixed at 768 dimensions
to match BAAI/bge-base (the current embedding model, per project config).

Changing embedding models later means a real migration (drop/recreate this
column at the new dimension, or add a second column during a transition
period, then backfill) — not a settings change. Vector dimension is a
schema decision, not a runtime one.
"""
import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import Computed, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from rag_persistence.db.base import Base
from rag_persistence.utils import generate_uuid, utcnow

EMBEDDING_DIM = 768  # BAAI/bge-base — see app/core/config.py EMBEDDING_DIMENSIONS


class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )

    processing_version: Mapped[str] = mapped_column(
        String(128), default="legacy", server_default="legacy", nullable=False
    )

    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)  # order within the document

    # "text" today; "image" (caption/OCR text), "audio" (transcript segment),
    # "video" (transcript segment + frame ref) once multimodal ingestion is
    # built — kept as a plain string for the same reason as Document.source_type.
    modality: Mapped[str] = mapped_column(String(50), default="text", nullable=False)

    content: Mapped[str] = mapped_column(Text, nullable=False)  # the actual text this chunk embeds
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM), nullable=False)

    # Sparse/keyword side of hybrid search. PostgreSQL GENERATED column —
    # Postgres maintains this automatically from `content`, no application
    # code writes to it. Paired with a GIN index (added by hand in the
    # migration, same reason as the HNSW index below) for full-text search
    # via plainto_tsquery(), combined with vector similarity in
    # ChunkRepository.hybrid_search() via reciprocal rank fusion.
    content_tsv: Mapped[str] = mapped_column(
        TSVECTOR, Computed("to_tsvector('english', content)", persisted=True), nullable=True
    )

    # page number, timestamp range (audio/video), bounding box (image), etc.
    chunk_metadata: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    document: Mapped["Document"] = relationship(back_populates="chunks")  # noqa: F821

    # Declared here (not just created via raw SQL in the migration) so
    # SQLAlchemy's metadata matches reality — without this, every future
    # `alembic revision --autogenerate` incorrectly proposes DROPping both
    # indexes, since it only trusts what's declared on the model, not what
    # actually exists in the database. Confirmed this was happening before
    # this fix; confirmed fixed after.
    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index", "processing_version", name="uq_chunks_document_index_processing_version"),
        Index(
            "ix_chunks_embedding_cosine",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        Index("ix_chunks_content_tsv", "content_tsv", postgresql_using="gin"),
    )
