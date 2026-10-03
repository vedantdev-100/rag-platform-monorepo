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

import redis.asyncio as redis

from app.db.session import AsyncSessionLocal
from app.logging import get_logger
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

    async def _handle(self, event: dict) -> None:
        event_type = event.get("event")
        user_id = event.get("user_id")
        if event_type == "user.deleted" and user_id:
            async with AsyncSessionLocal() as session:
                deleted = await DocumentRepository(session).delete_all_for_owner(uuid.UUID(user_id))
                logger.info("user_deleted_documents_purged", user_id=user_id, documents_deleted=deleted)
        elif event_type == "user.deactivated":
            # Deliberately no data deletion — a deactivated account can be
            # reactivated, and deactivation alone shouldn't destroy data.
            logger.info("user_deactivated_event_received", user_id=user_id)
        elif event_type == "user.reactivated":
            logger.info("user_reactivated_event_received", user_id=user_id)
        else:
            logger.warning("unknown_user_event", event=event)

    async def run(self) -> None:
        self._running = True
        await self._ensure_group()
        logger.info("user_event_consumer_started", consumer=self._consumer_name)
        while self._running:
            try:
                response = await self._redis.xreadgroup(
                    groupname=self._group, consumername=self._consumer_name,
                    streams={self._stream: ">"}, count=10, block=5000,
                )
                for _stream_name, messages in response:
                    for message_id, fields in messages:
                        try:
                            event = json.loads(fields[b"data"])
                            await self._handle(event)
                            await self._redis.xack(self._stream, self._group, message_id)
                        except Exception:
                            # Don't ack — redelivered on the next read instead
                            # of being silently dropped.
                            logger.exception("user_event_processing_failed", message_id=message_id)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("user_event_consumer_loop_error")
                await asyncio.sleep(2)  # back off before retrying the connection

    async def stop(self) -> None:
        self._running = False
        await self._redis.aclose()