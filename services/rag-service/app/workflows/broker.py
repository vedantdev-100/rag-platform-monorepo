"""Outbox delivery and Redis consumer plumbing. Publication is at-least-once."""
import asyncio
import hashlib
import json
import socket
import uuid
from datetime import timedelta

import redis.asyncio as redis
from sqlalchemy import and_, or_, select, update

from app.core.config import get_settings
from app.db.session import AsyncSessionLocal
from app.logging import get_logger
from app.workflows.state import DLQ, PUBLISH, put_message
from rag_contracts import IngestionJob
from rag_persistence.models.outbox import OutboxMessage
from rag_persistence.utils import utcnow

logger = get_logger(__name__)


def redis_client():
    return redis.from_url(get_settings().REDIS_URL, socket_connect_timeout=5, socket_timeout=10)


async def ensure_group(client):
    settings = get_settings()
    try:
        await client.xgroup_create(settings.INGESTION_STREAM, settings.INGESTION_CONSUMER_GROUP, id="0", mkstream=True)
    except redis.ResponseError as exc:
        if "BUSYGROUP" not in str(exc):
            raise


async def publish_once(client, *, message_id=None):
    settings, token, now = get_settings(), uuid.uuid4().hex, utcnow()
    async with AsyncSessionLocal() as session:
        async with session.begin():
            query = select(OutboxMessage).where(
                OutboxMessage.kind.in_([PUBLISH, DLQ]),
                or_(and_(OutboxMessage.status == "pending", OutboxMessage.available_at <= now),
                    and_(OutboxMessage.status == "publishing", OutboxMessage.locked_until <= now)),
            ).order_by(OutboxMessage.available_at, OutboxMessage.id).with_for_update(skip_locked=True).limit(1)
            if message_id is not None:
                query = query.where(OutboxMessage.id == message_id)
            message = (await session.execute(query)).scalar_one_or_none()
            if message is None:
                return False
            message.status = "publishing"
            message.locked_by = token
            message.locked_until = now + timedelta(seconds=60)
            message.attempts += 1
            identity, payload, kind, attempts = message.id, message.payload, message.kind, message.attempts
    error = None
    try:
        stream = settings.INGESTION_STREAM if kind == PUBLISH else settings.INGESTION_DLQ_STREAM
        # Never trim pending stream entries during publication. Retention is
        # an explicit operational policy, not an arbitrary maxlen here.
        await client.xadd(stream, {"data": json.dumps(payload, separators=(",", ":"))})
    except Exception as exc:
        error = type(exc).__name__
    async with AsyncSessionLocal() as session:
        async with session.begin():
            values = {"locked_by": None, "locked_until": None, "updated_at": utcnow()}
            if error is None:
                values.update(status="published", published_at=utcnow(), last_error=None)
            else:
                values.update(status="pending", last_error=error,
                              available_at=utcnow() + timedelta(seconds=min(60, 2 ** min(attempts, 5))))
            await session.execute(update(OutboxMessage).where(
                OutboxMessage.id == identity, OutboxMessage.locked_by == token,
            ).values(**values))
    if error:
        logger.warning("ingestion_publication_retry", outbox_id=str(identity), error_type=error)
    return True


async def publication_loop():
    client = redis_client()
    try:
        while True:
            try:
                if not await publish_once(client):
                    await asyncio.sleep(1)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("ingestion_publication_loop_error", error_type=type(exc).__name__)
                await asyncio.sleep(2)
    finally:
        await client.aclose()


async def quarantine(message_id, raw):
    settings = get_settings()
    identity = hashlib.sha256(f"{settings.INGESTION_STREAM}:{message_id}".encode()).hexdigest()
    if isinstance(raw, bytes):
        raw = raw.decode(errors="replace")
    async with AsyncSessionLocal() as session:
        async with session.begin():
            await put_message(session, kind=DLQ, key=f"bad-job:{identity}",
                              payload={"v": 1, "reason": "invalid_job_envelope",
                                       "message_id": str(message_id), "raw": str(raw)[:4096]})


async def ingestion_loop():
    from app.workflows.execution import process_job
    settings = get_settings()
    client = redis_client()
    consumer = f"{socket.gethostname()}-{uuid.uuid4().hex[:8]}"
    cursor, ready = "0-0", False
    async def process(messages):
        for message_id, fields in messages:
            try:
                raw = fields.get(b"data", b"")
                try:
                    job = IngestionJob.from_json(raw)
                except (ValueError, TypeError, KeyError, AttributeError):
                    await quarantine(message_id, raw)
                else:
                    await process_job(job)
                # Success, durable retry/DLQ, or a fenced duplicate has been
                # handled. DB errors/lease loss leave delivery pending.
                await client.xack(settings.INGESTION_STREAM, settings.INGESTION_CONSUMER_GROUP, message_id)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("ingestion_delivery_pending", error_type=type(exc).__name__)
    try:
        while True:
            try:
                if not ready:
                    await ensure_group(client)
                    ready = True
                    logger.info("ingestion_consumer_started", stream=settings.INGESTION_STREAM,
                                consumer_group=settings.INGESTION_CONSUMER_GROUP)
                claimed = await client.xautoclaim(
                    settings.INGESTION_STREAM, settings.INGESTION_CONSUMER_GROUP, consumer,
                    min_idle_time=settings.INGESTION_LEASE_SECONDS * 1000, start_id=cursor, count=1,
                )
                cursor = claimed[0]
                await process(claimed[1])
                response = await client.xreadgroup(settings.INGESTION_CONSUMER_GROUP, consumer,
                                                  {settings.INGESTION_STREAM: ">"}, count=1, block=5000)
                for _stream, messages in response:
                    await process(messages)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if isinstance(exc, redis.ResponseError) and "NOGROUP" in str(exc):
                    ready = False
                logger.error("ingestion_consumer_loop_error", error_type=type(exc).__name__)
                await asyncio.sleep(2)
    finally:
        await client.aclose()
