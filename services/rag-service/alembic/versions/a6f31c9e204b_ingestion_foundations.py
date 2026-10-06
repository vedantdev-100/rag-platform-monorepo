"""Add durable ingestion and object-storage schema foundations.

Revision ID: a6f31c9e204b
Revises: ede8cc507e7c

Existing document statuses, vectors, FTS/HNSW indexes and local source_uri
values remain unchanged. Provider metadata stays NULL when unknown.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "a6f31c9e204b"
down_revision = "ede8cc507e7c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Project-sized maintenance migration: avoid indefinite lock waits.
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute("LOCK TABLE rag.documents, rag.chunks IN ACCESS EXCLUSIVE MODE")
    # Fail before changes rather than silently discard duplicate old chunks.
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM rag.chunks
                GROUP BY document_id, chunk_index HAVING COUNT(*) > 1
            ) THEN
                RAISE EXCEPTION 'Duplicate legacy chunk positions found. Stop and review existing chunks before applying a6f31c9e204b.';
            END IF;
        END; $$;
    """)
    op.add_column("documents", sa.Column('object_bucket', sa.String(255), nullable=True), schema="rag")
    op.add_column("documents", sa.Column('object_key', sa.Text, nullable=True), schema="rag")
    op.add_column("documents", sa.Column('checksum', sa.String(128), nullable=True), schema="rag")
    op.add_column("documents", sa.Column('mime_type', sa.String(255), nullable=True), schema="rag")
    op.add_column("documents", sa.Column('file_size_bytes', sa.BigInteger, nullable=True), schema="rag")
    op.add_column("documents", sa.Column('failure_reason', sa.Text, nullable=True), schema="rag")
    op.add_column("documents", sa.Column('retry_count', sa.Integer, server_default=sa.text('0'), nullable=False), schema="rag")
    op.add_column("documents", sa.Column('generation', sa.Integer, server_default=sa.text('0'), nullable=False), schema="rag")
    op.add_column("documents", sa.Column('processing_version', sa.String(128), server_default='legacy', nullable=False), schema="rag")
    op.add_column("documents", sa.Column('job_id', postgresql.UUID(as_uuid=True), nullable=True), schema="rag")
    op.add_column("documents", sa.Column('processing_token', postgresql.UUID(as_uuid=True), nullable=True), schema="rag")
    op.add_column("documents", sa.Column('processing_lease_until', sa.DateTime(timezone=True), nullable=True), schema="rag")
    op.add_column("documents", sa.Column('next_retry_at', sa.DateTime(timezone=True), nullable=True), schema="rag")
    op.add_column("documents", sa.Column('parser_provider', sa.String(50), nullable=True), schema="rag")
    op.add_column("documents", sa.Column('parser_version', sa.String(128), nullable=True), schema="rag")
    op.add_column("documents", sa.Column('parser_task_id', sa.String(255), nullable=True), schema="rag")
    op.add_column("documents", sa.Column('chunking_strategy', sa.String(50), nullable=True), schema="rag")
    op.add_column("documents", sa.Column('chunking_version', sa.String(128), nullable=True), schema="rag")
    op.add_column("documents", sa.Column('embedding_model', sa.String(255), nullable=True), schema="rag")
    op.add_column("documents", sa.Column('embedding_model_revision', sa.String(128), nullable=True), schema="rag")
    op.add_column("documents", sa.Column('embedding_dimension', sa.Integer, nullable=True), schema="rag")
    op.add_column("documents", sa.Column('processed_at', sa.DateTime(timezone=True), nullable=True), schema="rag")
    op.create_check_constraint("ck_documents_retry_count_nonnegative", "documents", "retry_count >= 0", schema="rag")
    op.create_check_constraint("ck_documents_generation_nonnegative", "documents", "generation >= 0", schema="rag")
    op.create_check_constraint("ck_documents_file_size_nonnegative", "documents", "file_size_bytes IS NULL OR file_size_bytes >= 0", schema="rag")
    op.create_check_constraint("ck_documents_embedding_dimension_positive", "documents", "embedding_dimension IS NULL OR embedding_dimension > 0", schema="rag")
    op.create_index("ix_documents_owner_status", "documents", ["owner_id", "status"], schema="rag")
    op.add_column("chunks", sa.Column("processing_version", sa.String(128), nullable=False, server_default="legacy"), schema="rag")
    op.create_unique_constraint("uq_chunks_document_index_processing_version", "chunks", ["document_id", "chunk_index", "processing_version"], schema="rag")
    op.create_table('outbox',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column('kind', sa.String(50), nullable=False),
        sa.Column('aggregate_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('owner_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('deduplication_key', sa.String(255), nullable=True),
        sa.Column('payload', postgresql.JSONB, nullable=False),
        sa.Column('status', sa.String(20), server_default='pending', nullable=False),
        sa.Column('attempts', sa.Integer, server_default=sa.text('0'), nullable=False),
        sa.Column('available_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('locked_by', sa.String(100), nullable=True),
        sa.Column('locked_until', sa.DateTime(timezone=True), nullable=True),
        sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_error', sa.Text, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.UniqueConstraint('deduplication_key', name='uq_outbox_deduplication_key'),
        sa.CheckConstraint('attempts >= 0', name='ck_outbox_attempts_nonnegative'),
        sa.CheckConstraint("status IN ('pending', 'publishing', 'published', 'failed')", name='ck_outbox_status'),
        schema="rag",
    )
    op.create_index('ix_outbox_ready', 'outbox', ['status', 'available_at'], schema="rag")
    op.create_index('ix_outbox_aggregate_id', 'outbox', ['aggregate_id'], schema="rag")
    op.create_table('user_lifecycle_state',
        sa.Column('user_id', postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column('is_deleted', sa.Boolean, server_default=sa.text('false'), nullable=False),
        sa.Column('last_event_id', sa.Text, nullable=True),
        sa.Column('last_event_type', sa.String(50), nullable=True),
        sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        schema="rag",
    )


def downgrade() -> None:
    # Only use before worker cutover or with a reviewed backup/rollback plan.
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.drop_table("user_lifecycle_state", schema="rag")
    op.drop_index("ix_outbox_aggregate_id", table_name="outbox", schema="rag")
    op.drop_index("ix_outbox_ready", table_name="outbox", schema="rag")
    op.drop_table("outbox", schema="rag")
    op.drop_constraint("uq_chunks_document_index_processing_version", "chunks", type_="unique", schema="rag")
    op.drop_column("chunks", "processing_version", schema="rag")
    op.drop_index("ix_documents_owner_status", table_name="documents", schema="rag")
    op.drop_constraint("ck_documents_embedding_dimension_positive", "documents", type_="check", schema="rag")
    op.drop_constraint("ck_documents_file_size_nonnegative", "documents", type_="check", schema="rag")
    op.drop_constraint("ck_documents_generation_nonnegative", "documents", type_="check", schema="rag")
    op.drop_constraint("ck_documents_retry_count_nonnegative", "documents", type_="check", schema="rag")
    op.drop_column("documents", 'processed_at', schema="rag")
    op.drop_column("documents", 'embedding_dimension', schema="rag")
    op.drop_column("documents", 'embedding_model_revision', schema="rag")
    op.drop_column("documents", 'embedding_model', schema="rag")
    op.drop_column("documents", 'chunking_version', schema="rag")
    op.drop_column("documents", 'chunking_strategy', schema="rag")
    op.drop_column("documents", 'parser_task_id', schema="rag")
    op.drop_column("documents", 'parser_version', schema="rag")
    op.drop_column("documents", 'parser_provider', schema="rag")
    op.drop_column("documents", 'next_retry_at', schema="rag")
    op.drop_column("documents", 'processing_lease_until', schema="rag")
    op.drop_column("documents", 'processing_token', schema="rag")
    op.drop_column("documents", 'job_id', schema="rag")
    op.drop_column("documents", 'processing_version', schema="rag")
    op.drop_column("documents", 'generation', schema="rag")
    op.drop_column("documents", 'retry_count', schema="rag")
    op.drop_column("documents", 'failure_reason', schema="rag")
    op.drop_column("documents", 'file_size_bytes', schema="rag")
    op.drop_column("documents", 'mime_type', schema="rag")
    op.drop_column("documents", 'checksum', schema="rag")
    op.drop_column("documents", 'object_key', schema="rag")
    op.drop_column("documents", 'object_bucket', schema="rag")
