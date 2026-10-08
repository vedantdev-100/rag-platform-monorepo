import asyncio
from uuid import UUID

from app.rag.generation.events import sse
from app.rag.generation.types import GenerationError


async def snapshot(document_id, owner_id):
    from app.db.session import AsyncSessionLocal
    from app.repositories.document_repository import DocumentRepository

    async with AsyncSessionLocal() as session:
        document = await DocumentRepository(session).get_by_id(document_id)
        if document is None or document.owner_id != UUID(owner_id):
            raise GenerationError("document_not_found", 404)
        return {
            "id": str(document.id),
            "status": document.status,
            "generation": document.generation,
            "retry_count": document.retry_count,
            "processed_at": document.processed_at.isoformat()
            if document.processed_at
            else None,
            "failure_reason": "Document processing failed"
            if document.status == "failed"
            else None,
        }


async def document_events(
    document_id, owner_id, settings, lease, guard, initial, request_id, read=snapshot
):
    previous = None
    try:
        async with asyncio.timeout(settings.RAG_DOCUMENT_EVENTS_MAX_SECONDS):
            current = initial
            while True:
                await guard()
                if current != previous:
                    yield sse("status", {"request_id": request_id, **current})
                    previous = current
                if current["status"] in {"ingested", "failed"}:
                    yield sse("done", {"request_id": request_id, **current})
                    return
                # Poll in short sessions; never hold one for the stream lifetime.
                await asyncio.sleep(settings.RAG_DOCUMENT_EVENTS_POLL_SECONDS)
                current = await read(document_id, owner_id)
                if current == previous:
                    yield ": heartbeat\n\n"
    except TimeoutError:
        yield sse(
            "end", {"request_id": request_id, "reason": "stream_ttl", "reconnect": True}
        )
    except GenerationError as exc:
        yield sse(
            "error", {"request_id": request_id, "code": exc.code, "retryable": False}
        )
    except Exception:
        yield sse(
            "error",
            {"request_id": request_id, "code": "status_unavailable", "retryable": True},
        )
    finally:
        await lease.release()
