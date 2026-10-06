"""Durable source cleanup, temporarily executed in the API process.

Intents commit with document deletion. Storage I/O runs after the transaction;
short leases allow safe retries after process restarts. The single worker will
own this loop at queue cutover.
"""
from __future__ import annotations

import asyncio
import hashlib
import uuid
from datetime import timedelta

from sqlalchemy import and_, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal
from app.logging import get_logger
from rag_persistence.models.document import Document
from rag_persistence.models.outbox import OutboxMessage
from rag_persistence.models.user_lifecycle_state import UserLifecycleState
from rag_persistence.utils import utcnow

logger = get_logger(__name__)
KIND = "source.delete"


async def lock_owner(session: AsyncSession, owner_id: uuid.UUID) -> UserLifecycleState:
    await session.execute(insert(UserLifecycleState).values(user_id=owner_id).on_conflict_do_nothing())
    return (await session.execute(
        select(UserLifecycleState).where(UserLifecycleState.user_id == owner_id)
        .with_for_update().execution_options(populate_existing=True)
    )).scalar_one()


async def enqueue_cleanup(session: AsyncSession, uri: str | None, *, document_id=None, owner_id=None,
                          not_before=None) -> None:
    if not uri:
        return
    dedup = f"source.delete:{hashlib.sha256(uri.encode()).hexdigest()}"
    await session.execute(insert(OutboxMessage).values(
        kind=KIND, aggregate_id=document_id, owner_id=owner_id,
        deduplication_key=dedup, payload={"uri": uri}, status="pending", available_at=not_before or utcnow(),
    ).on_conflict_do_update(
        index_elements=[OutboxMessage.deduplication_key],
        set_={"status": "pending", "available_at": not_before or utcnow(), "locked_by": None,
              "locked_until": None, "published_at": None, "updated_at": utcnow()},
    ))


async def record_unattached_source(uri: str, *, document_id=None, owner_id=None) -> None:
    """Use an independent transaction after an ingestion transaction fails."""
    try:
        async with AsyncSessionLocal() as session:
            async with session.begin():
                await enqueue_cleanup(session, uri, document_id=document_id, owner_id=owner_id)
    except Exception as exc:
        # No credentials or SQL parameters in the error log.
        logger.error("source_cleanup_intent_failed", document_id=str(document_id), error_type=type(exc).__name__)


async def cleanup_once(storage=None, *, source_uri: str | None = None) -> bool:
    token = uuid.uuid4().hex
    now = utcnow()
    async with AsyncSessionLocal() as session:
        async with session.begin():
            query = select(OutboxMessage).where(
                    OutboxMessage.kind == KIND,
                    or_(and_(OutboxMessage.status == "pending", OutboxMessage.available_at <= now),
                        and_(OutboxMessage.status == "publishing", OutboxMessage.locked_until < now)),
                ).order_by(OutboxMessage.available_at, OutboxMessage.id).with_for_update(skip_locked=True).limit(1)
            if source_uri is not None:
                query = query.where(OutboxMessage.payload["uri"].astext == source_uri)
            message = (await session.execute(query)).scalar_one_or_none()
            if message is None:
                return False
            message.status = "publishing"
            message.locked_by = token
            message.locked_until = now + timedelta(minutes=3)
            message.attempts += 1
            message_id, uri, attempts = message.id, message.payload["uri"], message.attempts
            # A commit can succeed even if the client lost its response. Do
            # not delete a source that still belongs to a persisted document.
            referenced = await session.scalar(select(Document.id).where(Document.source_uri == uri).limit(1))
    error = None
    if referenced is None:
        try:
            if storage is None:
                from app.rag.ingestion.storage_factory import build_file_storage
                storage = build_file_storage()
            await storage.delete(uri)
        except Exception as exc:
            error = type(exc).__name__
    async with AsyncSessionLocal() as session:
        async with session.begin():
            values = {"locked_by": None, "locked_until": None, "updated_at": utcnow()}
            if error is None:
                values.update(status="published", published_at=utcnow(), last_error=None)
            else:
                values.update(status="pending", last_error=error,
                              available_at=utcnow() + timedelta(seconds=min(300, 2 ** min(attempts, 8))))
            result = await session.execute(update(OutboxMessage).where(
                OutboxMessage.id == message_id, OutboxMessage.locked_by == token,
            ).values(**values))
    if error:
        logger.warning("source_cleanup_retry_scheduled", outbox_id=str(message_id), error_type=error)
    elif result.rowcount:
        logger.info("source_cleanup_completed", outbox_id=str(message_id), source_still_referenced=referenced is not None)
    return True


async def run_cleanup() -> None:
    while True:
        try:
            found = await cleanup_once()
            if not found:
                await asyncio.sleep(3)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("source_cleanup_loop_error", error_type=type(exc).__name__)
            await asyncio.sleep(3)
