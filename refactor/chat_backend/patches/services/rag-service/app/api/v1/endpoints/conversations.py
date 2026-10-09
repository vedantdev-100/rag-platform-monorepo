from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from platform_auth import AuthenticatedUser, require_scopes
from starlette.background import BackgroundTask
from starlette.responses import StreamingResponse
from app.chat.events import chat_events
from app.chat.repository import ChatError, ChatRepository
from app.chat.schemas import CreateConversation, UpdateConversation, SelectDocuments, ChatTurn, ConversationOut, ConversationPage, MessagePage, RunOut
from app.chat.service import ChatService
from app.chat.settings import get_chat_settings
from app.core.rate_limit import limiter
from app.db.session import AsyncSessionLocal
from app.api.v1.endpoints.generation import service_for, unavailable
from app.rag.generation.auth import authorization_guard
from app.rag.generation.events import HEADERS, sse
from app.rag.generation.service import noop, reserve
from app.rag.generation.settings import get_generation_settings
from app.rag.generation.types import GenerationError

router = APIRouter(prefix='/conversations', tags=['conversations'])
settings = get_chat_settings()
generation_settings = get_generation_settings()
user_dependency = require_scopes('rag:query')

def repo_for(request):
    # Explicit test seam; production always uses the configured SQL session factory.
    return getattr(request.app.state, 'chat_repository', None) or ChatRepository(AsyncSessionLocal)

async def call(awaitable):
    try: return await awaitable
    except ChatError as exc: raise HTTPException(exc.status, {'code': exc.code}) from exc

@router.post('', status_code=201, response_model=ConversationOut)
@limiter.limit(settings.RATE_LIMIT_CHAT_MUTATION)
async def create(request: Request, payload: CreateConversation,
                 user: AuthenticatedUser = Depends(user_dependency)):
    return await call(repo_for(request).create(UUID(str(user.id)), payload))

@router.get('', response_model=ConversationPage)
async def list_chats(request: Request, limit: int = Query(20, ge=1, le=100),
                     offset: int = Query(0, ge=0, le=100000), archived: bool = False,
                     user: AuthenticatedUser = Depends(user_dependency)):
    return await call(repo_for(request).list(UUID(str(user.id)), limit, offset, archived))

@router.get('/{conversation_id}', response_model=ConversationOut)
async def get_chat(request: Request, conversation_id: UUID,
                   user: AuthenticatedUser = Depends(user_dependency)):
    return await call(repo_for(request).get(UUID(str(user.id)), conversation_id))

@router.patch('/{conversation_id}', response_model=ConversationOut)
@limiter.limit(settings.RATE_LIMIT_CHAT_MUTATION)
async def update(request: Request, conversation_id: UUID, payload: UpdateConversation,
                 user: AuthenticatedUser = Depends(user_dependency)):
    return await call(repo_for(request).update(UUID(str(user.id)), conversation_id, payload))

@router.delete('/{conversation_id}', status_code=204)
@limiter.limit(settings.RATE_LIMIT_CHAT_MUTATION)
async def delete_chat(request: Request, conversation_id: UUID,
                      user: AuthenticatedUser = Depends(user_dependency)):
    await call(repo_for(request).delete(UUID(str(user.id)), conversation_id))
    return Response(status_code=204)

@router.put('/{conversation_id}/documents', response_model=ConversationOut)
@limiter.limit(settings.RATE_LIMIT_CHAT_MUTATION)
async def documents(request: Request, conversation_id: UUID, payload: SelectDocuments,
                    user: AuthenticatedUser = Depends(user_dependency)):
    return await call(repo_for(request).select_documents(UUID(str(user.id)), conversation_id, payload))

@router.get('/{conversation_id}/messages', response_model=MessagePage)
async def history(request: Request, conversation_id: UUID,
                  limit: int = Query(50, ge=1, le=100), before: int | None = Query(None, ge=1),
                  user: AuthenticatedUser = Depends(user_dependency)):
    return await call(repo_for(request).history(UUID(str(user.id)), conversation_id, limit, before))

@router.get('/{conversation_id}/runs/{run_id}', response_model=RunOut)
async def run_status(request: Request, conversation_id: UUID, run_id: UUID,
                     user: AuthenticatedUser = Depends(user_dependency)):
    return await call(repo_for(request).run_status(UUID(str(user.id)), conversation_id, run_id))

@router.post('/{conversation_id}/runs/{run_id}/cancel', status_code=204)
@limiter.limit(settings.RATE_LIMIT_CHAT_MUTATION)
async def cancel(request: Request, conversation_id: UUID, run_id: UUID,
                 user: AuthenticatedUser = Depends(user_dependency)):
    repo = repo_for(request); owner = UUID(str(user.id))
    await call(repo.run_status(owner, conversation_id, run_id))
    await call(repo.fail(owner, conversation_id, run_id, 'cancelled', 'generation_cancelled'))
    return Response(status_code=204)

async def replay_events(turn, guard):
    await guard()
    # Explicit replay result; never restart the provider for the same client ID.
    yield sse('replay', turn)

async def prepare(request, payload, owner, cid):
    generation = service_for(request)
    guard = authorization_guard(request, str(owner))
    lease = None
    try:
        await guard()
        lease = await reserve(generation.capacity)
        repo = repo_for(request)
        turn = await repo.begin(owner, cid, payload)
        return ChatService(repo, generation), guard, lease, turn
    except BaseException:
        if lease: await lease.release()
        raise

@router.post('/{conversation_id}/messages', response_model=RunOut)
@limiter.limit(generation_settings.RATE_LIMIT_GENERATION)
async def send(request: Request, conversation_id: UUID, payload: ChatTurn,
               user: AuthenticatedUser = Depends(user_dependency)):
    lease = None
    try:
        service, guard, lease, turn = await prepare(request, payload, UUID(str(user.id)), conversation_id)
        if turn['replay']: return turn
        return await service.execute(turn, payload, UUID(str(user.id)), conversation_id, emit=noop, guard=guard)
    except ChatError as exc: raise HTTPException(exc.status, {'code': exc.code}) from exc
    except GenerationError as exc: raise unavailable(exc) from exc
    finally:
        if lease: await lease.release()

@router.post('/{conversation_id}/messages/stream')
@limiter.limit(generation_settings.RATE_LIMIT_GENERATION)
async def stream(request: Request, conversation_id: UUID, payload: ChatTurn,
                 user: AuthenticatedUser = Depends(user_dependency)):
    try:
        service, guard, lease, turn = await prepare(request, payload, UUID(str(user.id)), conversation_id)
    except ChatError as exc: raise HTTPException(exc.status, {'code': exc.code}) from exc
    except GenerationError as exc: raise unavailable(exc) from exc
    if turn['replay']:
        await lease.release()
        return StreamingResponse(replay_events(turn, guard), media_type='text/event-stream', headers=HEADERS)
    return StreamingResponse(chat_events(service, lease, turn, payload, UUID(str(user.id)), conversation_id, guard),
        media_type='text/event-stream', headers=HEADERS, background=BackgroundTask(lease.release))
