"""Print queue counts and database number without printing credentials or payloads."""
import asyncio
import redis.asyncio as redis

from app.core.config import get_settings


async def main():
    settings = get_settings()
    client = redis.from_url(settings.REDIS_URL, socket_connect_timeout=5, socket_timeout=10)
    try:
        print("Redis DB:", client.connection_pool.connection_kwargs.get("db", 0))
        print("Ingestion stream:", settings.INGESTION_STREAM)
        print("Retained entries:", await client.xlen(settings.INGESTION_STREAM))
        print("Consumer group:", settings.INGESTION_CONSUMER_GROUP)
        try:
            pending = await client.xpending(settings.INGESTION_STREAM, settings.INGESTION_CONSUMER_GROUP)
            print("Pending delivered entries:", pending["pending"])
        except redis.ResponseError:
            print("Consumer group not initialized; start rag-worker and inspect its logs.")
        print("Dead-letter stream:", settings.INGESTION_DLQ_STREAM)
        print("Dead-letter entries:", await client.xlen(settings.INGESTION_DLQ_STREAM))
    finally:
        await client.aclose()


if __name__ == '__main__':
    asyncio.run(main())
