"""
A Document is one ingested source — a PDF, a web page, an image, an audio
or video file. It doesn't hold embeddings itself; it's split into Chunk
rows (app/models/chunk.py), each with its own embedding, since retrieval
operates at chunk granularity.
"""
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from rag_persistence.db.base import Base
from rag_persistence.utils import generate_uuid, utcnow


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)

    # Who ingested it — reuses the existing auth system; scoped access to a
    # document's chunks should check this, not just "any authenticated user".
    # owner_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)

    # No FK into auth.users: identity ownership and cleanup are event-driven,
    # keeping this service independent of auth-schema queries/permissions.
    owner_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True),nullable=False,index=True,)

    title: Mapped[str] = mapped_column(String(500), nullable=False)

    # "text" | "pdf" | "image" | "audio" | "video" | "url" — kept as a plain
    # string rather than a DB enum so adding a new modality is a code change,
    # not a migration.
    source_type: Mapped[str] = mapped_column(String(50), nullable=False)
    source_uri: Mapped[str] = mapped_column(Text, nullable=True)  # file path, URL, or object-store key

    # "pending" -> "processing" -> "ingested" | "failed" — ingestion pipeline
    # state. A document with chunks isn't necessarily "ready"; check this.
    status: Mapped[str] = mapped_column(String(50), default="pending", nullable=False)

    # Free-form: page count, author, MIME type, duration (for audio/video), etc.
    doc_metadata: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    # Additive workflow fields; existing local rows keep unknown provenance.
    object_bucket: Mapped[str | None] = mapped_column(String(255), nullable=True)
    object_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    checksum: Mapped[str | None] = mapped_column(String(128), nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    file_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"), nullable=False)
    generation: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"), nullable=False)
    processing_version: Mapped[str] = mapped_column(String(128), default="legacy", server_default="legacy", nullable=False)
    job_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    processing_token: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    processing_lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    parser_provider: Mapped[str | None] = mapped_column(String(50), nullable=True)
    parser_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    parser_task_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    chunking_strategy: Mapped[str | None] = mapped_column(String(50), nullable=True)
    chunking_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    embedding_model_revision: Mapped[str | None] = mapped_column(String(128), nullable=True)
    embedding_dimension: Mapped[int | None] = mapped_column(Integer, nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    chunks: Mapped[list["Chunk"]] = relationship(back_populates="document", cascade="all, delete-orphan")

    __table_args__ = (
        CheckConstraint("retry_count >= 0", name="ck_documents_retry_count_nonnegative"),
        CheckConstraint("generation >= 0", name="ck_documents_generation_nonnegative"),
        CheckConstraint("file_size_bytes IS NULL OR file_size_bytes >= 0", name="ck_documents_file_size_nonnegative"),
        CheckConstraint("embedding_dimension IS NULL OR embedding_dimension > 0", name="ck_documents_embedding_dimension_positive"),
        Index("ix_documents_owner_status", "owner_id", "status"),
    )


from rag_persistence.models.chunk import Chunk  # noqa: E402  (avoid circular import at module load)
