"""Application-owned chat history; no LangGraph dependency in the worker."""
import uuid
from datetime import datetime

from sqlalchemy import (Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer,
                        String, Text, UniqueConstraint, text)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from rag_persistence.db.base import Base


class Conversation(Base):
    __tablename__ = 'conversations'
    __table_args__ = (
        CheckConstraint("document_scope IN ('selected', 'all_owner')", name='ck_conversation_scope'),
        Index('ix_conversations_owner_updated', 'owner_id', 'updated_at'),
        {'schema': 'rag'},
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False, default='New chat')
    archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text('false'))
    document_scope: Mapped[str] = mapped_column(String(20), nullable=False, default='selected')
    next_sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default=text('1'))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text('now()'))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text('now()'))


class ConversationDocument(Base):
    __tablename__ = 'conversation_documents'
    __table_args__ = {'schema': 'rag'}
    conversation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('rag.conversations.id', ondelete='CASCADE'), primary_key=True)
    document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('rag.documents.id', ondelete='CASCADE'), primary_key=True)


class GenerationRun(Base):
    __tablename__ = 'generation_runs'
    __table_args__ = (
        UniqueConstraint('conversation_id', 'client_message_id', name='uq_chat_client_message'),
        CheckConstraint("status IN ('running','completed','failed','cancelled')", name='ck_chat_run_status'),
        Index('uq_chat_active_run', 'conversation_id', unique=True, postgresql_where=text("status = 'running'")),
        {'schema': 'rag'},
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('rag.conversations.id', ondelete='CASCADE'), nullable=False)
    client_message_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default='running')
    lease_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    document_ids: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text('now()'))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text('now()'))


class ChatMessage(Base):
    __tablename__ = 'chat_messages'
    __table_args__ = (
        UniqueConstraint('conversation_id', 'sequence', name='uq_chat_message_sequence'),
        CheckConstraint("role IN ('user','assistant')", name='ck_chat_message_role'),
        CheckConstraint("status IN ('pending','completed','failed','cancelled')", name='ck_chat_message_status'),
        Index('ix_chat_messages_run', 'run_id'),
        {'schema': 'rag'},
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('rag.conversations.id', ondelete='CASCADE'), nullable=False)
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('rag.generation_runs.id', ondelete='CASCADE'), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, default='')
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    answer: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text('now()'))
