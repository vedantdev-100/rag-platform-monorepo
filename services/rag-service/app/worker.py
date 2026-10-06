"""One worker process: lifecycle/cleanup, ingestion, publication and recovery."""
import asyncio
import signal

from app.core.config import get_settings
from app.db.session import engine
from app.events.consumer import UserEventConsumer
from app.logging import configure_logging, get_logger
from app.workflows.broker import ingestion_loop, publication_loop
from app.workflows.execution import reconciliation_loop


async def serve() -> None:
    settings = get_settings()
    if not settings.RUN_LIFECYCLE_CONSUMER:
        raise RuntimeError("rag-worker requires RUN_LIFECYCLE_CONSUMER=true")
    configure_logging(debug=settings.DEBUG)
    logger = get_logger(__name__)
    stop_requested = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_requested.set)
    consumer = UserEventConsumer(
        settings.REDIS_URL, settings.USER_EVENTS_STREAM, settings.USER_EVENTS_CONSUMER_GROUP,
    )
    tasks = {
        asyncio.create_task(consumer.run(), name="lifecycle-and-source-cleanup"),
        asyncio.create_task(ingestion_loop(), name="ingestion"),
        asyncio.create_task(publication_loop(), name="outbox-publication"),
        asyncio.create_task(reconciliation_loop(), name="ingestion-reconciliation"),
    }
    stop_task = asyncio.create_task(stop_requested.wait(), name="worker-stop")
    logger.info("rag_worker_started", stream=settings.USER_EVENTS_STREAM,
                ingestion_stream=settings.INGESTION_STREAM,
                consumer_group=settings.INGESTION_CONSUMER_GROUP)
    try:
        done, _ = await asyncio.wait(tasks | {stop_task}, return_when=asyncio.FIRST_COMPLETED)
        if stop_task not in done:
            for task in done:
                await task
            raise RuntimeError("A required worker loop exited unexpectedly")
    finally:
        stop_task.cancel()
        for task in tasks:
            task.cancel()
        await asyncio.gather(stop_task, *tasks, return_exceptions=True)
        await consumer.stop()
        await engine.dispose()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.remove_signal_handler(sig)
        logger.info("rag_worker_stopped")


if __name__ == "__main__":
    asyncio.run(serve())
