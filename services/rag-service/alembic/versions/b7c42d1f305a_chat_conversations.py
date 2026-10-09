"""Durable conversations, document selections, messages and fenced runs.

Revision ID: b7c42d1f305a
Revises: a6f31c9e204b
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB
revision = 'b7c42d1f305a'
down_revision = 'a6f31c9e204b'
branch_labels = None
depends_on = None

def upgrade():
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.create_table('conversations',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('owner_id', UUID(as_uuid=True), nullable=False),
        sa.Column('title', sa.String(200), nullable=False),
        sa.Column('archived', sa.Boolean, nullable=False, server_default=sa.text('false')),
        sa.Column('document_scope', sa.String(20), nullable=False),
        sa.Column('next_sequence', sa.Integer, nullable=False, server_default=sa.text('1')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.CheckConstraint("document_scope IN ('selected','all_owner')", name='ck_conversation_scope'), schema='rag')
    op.create_index('ix_conversations_owner_updated', 'conversations', ['owner_id','updated_at'], schema='rag')
    op.create_table('conversation_documents',
        sa.Column('conversation_id', UUID(as_uuid=True), sa.ForeignKey('rag.conversations.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('document_id', UUID(as_uuid=True), sa.ForeignKey('rag.documents.id', ondelete='CASCADE'), primary_key=True), schema='rag')
    op.create_table('generation_runs',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('conversation_id', UUID(as_uuid=True), sa.ForeignKey('rag.conversations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('client_message_id', UUID(as_uuid=True), nullable=False),
        sa.Column('payload_hash', sa.String(64), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('lease_until', sa.DateTime(timezone=True), nullable=False),
        sa.Column('error_code', sa.String(80)), sa.Column('document_ids', JSONB),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.UniqueConstraint('conversation_id','client_message_id',name='uq_chat_client_message'),
        sa.CheckConstraint("status IN ('running','completed','failed','cancelled')",name='ck_chat_run_status'), schema='rag')
    op.create_index('uq_chat_active_run','generation_runs',['conversation_id'],schema='rag',unique=True,
                    postgresql_where=sa.text("status = 'running'"))
    op.create_table('chat_messages',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('conversation_id', UUID(as_uuid=True), sa.ForeignKey('rag.conversations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('run_id', UUID(as_uuid=True), sa.ForeignKey('rag.generation_runs.id', ondelete='CASCADE'), nullable=False),
        sa.Column('sequence', sa.Integer, nullable=False), sa.Column('role',sa.String(20),nullable=False),
        sa.Column('content',sa.Text,nullable=False), sa.Column('status',sa.String(20),nullable=False),
        sa.Column('answer',JSONB),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False,server_default=sa.text('now()')),
        sa.UniqueConstraint('conversation_id','sequence',name='uq_chat_message_sequence'),
        sa.CheckConstraint("role IN ('user','assistant')",name='ck_chat_message_role'),
        sa.CheckConstraint("status IN ('pending','completed','failed','cancelled')",name='ck_chat_message_status'),schema='rag')
    op.create_index('ix_chat_messages_run','chat_messages',['run_id'],schema='rag')

def downgrade():
    # Destructive: chat history is lost. Prefer code rollback with tables retained.
    op.drop_table('chat_messages',schema='rag')
    op.drop_table('generation_runs',schema='rag')
    op.drop_table('conversation_documents',schema='rag')
    op.drop_table('conversations',schema='rag')
