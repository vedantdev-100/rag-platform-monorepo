from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from platform_auth import AuthenticatedUser, require_scopes
from starlette.background import BackgroundTask
from starlette.responses import StreamingResponse

from app.core.rate_limit import limiter
from app.rag.generation.auth import authorization_guard
from app.rag.generation.events import HEADERS, generation_events
from app.rag.generation.service import reserve
from app.rag.generation.settings import get_generation_settings
from app.rag.generation.types import GenerationError
from app.schemas.generation import GenerationRequest, GenerationResponse

router = APIRouter(prefix="/generation", tags=["generation"])
settings = get_generation_settings()


def unavailable(exc):
    headers = (
        {"Retry-After": str(exc.retry_after)} if exc.retry_after is not None else None
    )
    return HTTPException(
        exc.status, {"code": exc.code, "retryable": exc.retryable}, headers=headers
    )


def service_for(request):
    service = getattr(request.app.state, "generation_service", None)
    if service is None:
        raise HTTPException(503, "generation_disabled")
    return service


@router.post("", response_model=GenerationResponse)
@limiter.limit(settings.RATE_LIMIT_GENERATION)
async def generate(
    request: Request,
    payload: GenerationRequest,
    current_user: AuthenticatedUser = Depends(require_scopes("rag:query")),
):
    service = service_for(request)
    owner_id = str(current_user.id)
    try:
        return await service.run(
            payload.query,
            owner_id,
            payload.top_k,
            guard=authorization_guard(request, owner_id),
        )
    except GenerationError as exc:
        raise unavailable(exc) from exc


@router.post("/stream")
@limiter.limit(settings.RATE_LIMIT_GENERATION)
async def generate_stream(
    request: Request,
    payload: GenerationRequest,
    current_user: AuthenticatedUser = Depends(require_scopes("rag:query")),
):
    service = service_for(request)
    owner_id = str(current_user.id)
    guard = authorization_guard(request, owner_id)
    try:
        await guard()
        lease = await reserve(service.capacity)
    except GenerationError as exc:
        raise unavailable(exc) from exc
    return StreamingResponse(
        generation_events(
            service, lease, payload.query, owner_id, payload.top_k, guard, str(uuid4())
        ),
        media_type="text/event-stream",
        headers=HEADERS,
        background=BackgroundTask(lease.release),
    )
