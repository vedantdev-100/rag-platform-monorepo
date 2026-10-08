import asyncio
import json

from app.rag.generation.types import GenerationError

HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


def sse(name, data):
    return f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def generation_events(service, lease, query, owner_id, top_k, guard, request_id):
    queue = asyncio.Queue(maxsize=service.settings.RAG_SSE_QUEUE_SIZE)

    async def emit(name, data):
        await queue.put((name, data))

    producer = asyncio.create_task(
        service.execute(
            query, owner_id, top_k, emit=emit, guard=guard, request_id=request_id
        )
    )
    reader = None
    try:
        yield sse("start", {"request_id": request_id})
        while True:
            if reader is None:
                reader = asyncio.create_task(queue.get())
            done, _ = await asyncio.wait(
                {reader, producer},
                timeout=service.settings.RAG_SSE_HEARTBEAT_SECONDS,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if not done:
                yield ": heartbeat\n\n"
                continue
            if producer not in done:
                name, data = reader.result()
                reader = None
                yield sse(name, data)
                continue
            # Resolve failure before forwarding queued data: a revoked request
            # must not drain buffered evidence/text after its watchdog stops it.
            pending = None
            if reader.done() and not reader.cancelled():
                pending = reader.result()
            else:
                reader.cancel()
                await asyncio.gather(reader, return_exceptions=True)
            reader = None
            try:
                answer = producer.result()
                await guard()
                if pending is not None:
                    yield sse(*pending)
                while not queue.empty():
                    yield sse(*queue.get_nowait())
                await guard()
                yield sse("done", answer.model_dump(mode="json"))
            except GenerationError as exc:
                yield sse(
                    "error",
                    {
                        "request_id": request_id,
                        "code": exc.code,
                        "retryable": exc.retryable,
                        "retry_after": exc.retry_after,
                        "discard_provisional": True,
                    },
                )
            break
    finally:
        producer.cancel()
        if reader:
            reader.cancel()
        await asyncio.gather(
            producer, *([reader] if reader else []), return_exceptions=True
        )
        await lease.release()
