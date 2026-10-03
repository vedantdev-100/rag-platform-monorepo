"""
Publishes user lifecycle events to a Redis Stream (not plain pub/sub — see
module docstring in rag-service's consumer.py for why durability matters
here specifically).
"""
import json
import uuid
from datetime import datetime, timezone

import redis.asyncio as redis


class UserEventPublisher:
    def __init__(self, redis_url: str, stream: str):
        self._redis = redis.from_url(redis_url)
        self._stream = stream

    async def _publish(self, event: str, user_id: uuid.UUID) -> None:
        payload = {
            "event": event,
            "user_id": str(user_id),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await self._redis.xadd(self._stream, {"data": json.dumps(payload)})

    async def publish_deactivated(self, user_id: uuid.UUID) -> None:
        await self._publish("user.deactivated", user_id)

    async def publish_deleted(self, user_id: uuid.UUID) -> None:
        await self._publish("user.deleted", user_id)

    async def close(self) -> None:
        await self._redis.aclose()