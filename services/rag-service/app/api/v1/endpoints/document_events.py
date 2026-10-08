import asyncio
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from platform_auth import AuthenticatedUser, require_scopes
from starlette.background import BackgroundTask
from starlette.responses import StreamingResponse

from app.core.rate_limit import limiter
from app.rag.generation.auth import authorization_guard
from app.rag.generation.document_status import document_events, snapshot
from app.rag.generation.events import HEADERS
from app.rag.generation.service import reserve
from app.rag.generation.settings import get_generation_settings
from app.rag.generation.types import GenerationError

router = APIRouter(prefix="/documents", tags=["documents"])
settings = get_generation_settings()


@router.get("/{document_id}/events")
@limiter.limit(settings.RATE_LIMIT_DOCUMENT_EVENTS)
async def stream_document_status(
    request: Request,
    document_id: UUID,
    current_user: AuthenticatedUser = Depends(require_scopes("rag:query")),
):
    owner_id = str(current_user.id)
    guard = authorization_guard(request, owner_id)
    lease = None
    try:
        if not hasattr(request.app.state, "document_events_capacity"):
            request.app.state.document_events_capacity = asyncio.Semaphore(
                settings.RAG_DOCUMENT_EVENTS_MAX_CONCURRENT
            )
        lease = await reserve(
            request.app.state.document_events_capacity, "document_events_busy"
        )
        async with asyncio.timeout(10):
            await guard()
            initial = await snapshot(document_id, owner_id)
    except GenerationError as exc:
        if lease:
            await lease.release()
        raise HTTPException(exc.status, exc.code) from exc
    except BaseException as exc:
        if lease:
            await lease.release()
        if isinstance(exc, asyncio.CancelledError):
            raise
        raise HTTPException(503, "status_unavailable") from exc
    return StreamingResponse(
        document_events(
            document_id, owner_id, settings, lease, guard, initial, str(uuid4())
        ),
        media_type="text/event-stream",
        headers=HEADERS,
        background=BackgroundTask(lease.release),
    )
