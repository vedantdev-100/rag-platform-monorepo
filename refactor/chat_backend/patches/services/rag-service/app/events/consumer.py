"""
Background consumer for user lifecycle events published by auth-service.
Uses a Redis Stream consumer group for at-least-once delivery: if this
service is down when an event is published, it's still in the stream and
gets delivered on reconnect rather than lost forever — critical here
because a missed "user.deleted" event means permanently orphaned
documents/chunks with no other mechanism to clean them up.
"""
import asyncio
import json
import socket
import uuid
from datetime import timedelta

import redis.asyncio as redis

from app.db.session import AsyncSessionLocal
from app.logging import get_logger
from sqlalchemy import delete, select
from rag_persistence.models.conversation import Conversation
from app.events.source_cleanup import enqueue_cleanup, lock_owner, run_cleanup
from rag_persistence.models.document import Document
from rag_persistence.utils import utcnow
from app.repositories.document_repository import DocumentRepository

logger = get_logger(__name__)


class UserEventConsumer:
    def __init__(self, redis_url: str, stream: str, group: str):
        self._redis = redis.from_url(redis_url)
        self._stream = stream
        self._group = group
        self._consumer_name = f"{socket.gethostname()}-{uuid.uuid4().hex[:8]}"  # unique per replica
        self._running = False

    async def _ensure_group(self) -> None:
        try:
            await self._redis.xgroup_create(self._stream, self._group, id="0", mkstream=True)
        except redis.ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise  # group already exists from a previous run — fine

    async def _handle(self, event: dict, event_id: str | None = None) -> None:
        event_type = event.get("event")
        user_id = event.get("user_id")
        if event_type == "user.deleted" and user_id:
            async with AsyncSessionLocal() as session:
                async with session.begin():
                    owner_id = uuid.UUID(str(user_id))
                    owner_state = await lock_owner(session, owner_id)
                    owner_state.is_deleted = True
                    owner_state.deleted_at = owner_state.deleted_at or utcnow()
                    owner_state.last_event_type = event_type
                    owner_state.last_event_id = event_id
                    sources = (await session.execute(
                        select(Document.id, Document.source_uri, Document.doc_metadata,
                               Document.processing_lease_until).where(Document.owner_id == owner_id)
                    )).all()
                    for document_id, uri, metadata, lease_until in sources:
                        # A source write can still be in flight. Its reservation
                        # bounds the write window; do not DELETE before PUT ends.
                        not_before = None
                        if metadata.get("source_ready") is False and lease_until is not None:
                            not_before = lease_until + timedelta(seconds=30)
                        await enqueue_cleanup(session, uri, document_id=document_id, owner_id=owner_id,
                                              not_before=not_before)
                    await session.execute(delete(Conversation).where(Conversation.owner_id == owner_id))
                    deleted = await DocumentRepository(session).delete_all_for_owner(owner_id)
                logger.info("user_deleted_documents_purged", user_id=user_id, documents_deleted=deleted)
        elif event_type == "user.deactivated":
            # Deliberately no data deletion — a deactivated account can be
            # reactivated, and deactivation alone shouldn't destroy data.
            logger.info("user_deactivated_event_received", user_id=user_id)
        elif event_type == "user.reactivated":
            logger.info("user_reactivated_event_received", user_id=user_id)
        else:
            logger.warning("unknown_user_event", event=event)

    async def _process(self, messages) -> None:
        for message_id, fields in messages:
            try:
                event = json.loads(fields[b"data"])
                event_id = message_id.decode() if isinstance(message_id, bytes) else str(message_id)
                await self._handle(event, event_id)
                # DB deletion and cleanup intent are committed before ACK.
                await self._redis.xack(self._stream, self._group, message_id)
            except Exception:
                logger.exception("user_event_processing_failed", message_id=message_id)

    async def run(self) -> None:
        self._running = True
        cleanup_task = asyncio.create_task(run_cleanup())
        group_ready = False
        claim_cursor = "0-0"
        try:
            while self._running:
                try:
                    if not group_ready:
                        await self._ensure_group()
                        group_ready = True
                        logger.info("user_event_consumer_started", consumer=self._consumer_name)
                    # Redis >=6.2: also recover pending messages from stopped
                    # consumers instead of reading only never-delivered entries.
                    claimed = await self._redis.xautoclaim(
                        self._stream, self._group, self._consumer_name,
                        min_idle_time=60000, start_id=claim_cursor, count=10,
                    )
                    claim_cursor = claimed[0]
                    await self._process(claimed[1])
                    response = await self._redis.xreadgroup(
                        groupname=self._group, consumername=self._consumer_name,
                        streams={self._stream: ">"}, count=10, block=5000,
                    )
                    for _stream_name, messages in response:
                        await self._process(messages)
                except asyncio.CancelledError:
                    break
                except Exception as exc:
                    if isinstance(exc, redis.ResponseError) and "NOGROUP" in str(exc):
                        group_ready = False
                    logger.exception("user_event_consumer_loop_error")
                    await asyncio.sleep(2)
        finally:
            cleanup_task.cancel()
            await asyncio.gather(cleanup_task, return_exceptions=True)

    async def stop(self) -> None:
        self._running = False
        await self._redis.aclose()