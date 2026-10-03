"""
A Document is one ingested source — a PDF, a web page, an image, an audio
or video file. It doesn't hold embeddings itself; it's split into Chunk
rows (app/models/chunk.py), each with its own embedding, since retrieval
operates at chunk granularity.
"""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.utils import generate_uuid, utcnow


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)

    # Who ingested it — reuses the existing auth system; scoped access to a
    # document's chunks should check this, not just "any authenticated user".
    # owner_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)

    # owner_id is NOT a foreign key to auth.users — cross-schema FKs aren't
    # supported with separate least-privilege roles. This is intentional:
    # rag-service trusts the JWT's `sub` claim rather than querying auth's
    # schema. A document can reference a user_id that no longer exists in
    # auth-service if that user was deleted — see "user deletion" below.
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

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    chunks: Mapped[list["Chunk"]] = relationship(back_populates="document", cascade="all, delete-orphan")


from app.models.chunk import Chunk  # noqa: E402  (avoid circular import at module load)
