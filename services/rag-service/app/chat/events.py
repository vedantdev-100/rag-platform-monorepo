import asyncio
from app.rag.generation.events import sse
from app.rag.generation.types import GenerationError

async def chat_events(service, lease, turn, payload, owner, cid, guard):
    queue = asyncio.Queue(maxsize=service.generation.settings.RAG_SSE_QUEUE_SIZE)
    async def emit(name, data):
        await queue.put((name, data))
    producer = asyncio.create_task(service.execute(turn, payload, owner, cid, emit=emit, guard=guard))
    reader = None
    ids = {'conversation_id': str(cid), 'run_id': turn['run_id'],
           'message_id': turn['messages'][1]['id']}
    try:
        yield sse('start', {**ids, 'client_message_id': turn['client_message_id'],
                            'user_message_id': turn['messages'][0]['id']})
        while True:
            if reader is None: reader = asyncio.create_task(queue.get())
            done, _ = await asyncio.wait({reader, producer},
                timeout=service.generation.settings.RAG_SSE_HEARTBEAT_SECONDS,
                return_when=asyncio.FIRST_COMPLETED)
            if not done:
                yield ': heartbeat\n\n'; continue
            if producer not in done:
                yield sse(*reader.result()); reader = None; continue
            pending = reader.result() if reader.done() and not reader.cancelled() else None
            if not reader.done():
                reader.cancel(); await asyncio.gather(reader, return_exceptions=True)
            reader = None
            try:
                result = producer.result()  # already committed the final answer
                await guard()
                if pending: yield sse(*pending)
                while not queue.empty(): yield sse(*queue.get_nowait())
                await guard()
                yield sse('done', {**ids, **result})
            except GenerationError as exc:
                yield sse('error', {**ids, 'code': exc.code, 'retryable': exc.retryable,
                    'retry_after': exc.retry_after, 'discard_provisional': True})
            break
    finally:
        producer.cancel()
        if reader: reader.cancel()
        await asyncio.gather(producer, *([reader] if reader else []), return_exceptions=True)
        await lease.release()
