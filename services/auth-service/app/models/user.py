import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.utils import generate_uuid, utcnow


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=True)

    # --- RBAC ---
    # `role` is coarse-grained (user/admin/service). `scopes` (comma-separated
    # or a separate table if it grows) is fine-grained, e.g. "rag:query,
    # rag:ingest" — designed now so future RAG endpoints can gate access
    # without a schema migration. This project is RAG-only; scopes stay
    # rag:*-namespaced (see AGENTS.md for the reasoning on the project split).
    role: Mapped[str] = mapped_column(String(50), default="user", nullable=False)
    scopes: Mapped[str] = mapped_column(String(500), default="", nullable=False)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    refresh_tokens: Mapped[list["RefreshToken"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

    def scope_list(self) -> list[str]:
        return [s for s in self.scopes.split(",") if s]


from app.models.refresh_token import RefreshToken  # noqa: E402  (avoid circular import at module load)
