import asyncio
import logging
import anyio
from uuid import UUID

from app.chat.repository import ChatError
from app.rag.generation.types import GenerationError

logger = logging.getLogger(__name__)

class ChatService:
    def __init__(self, repository, generation):
        self.repository, self.generation = repository, generation

    async def execute(self, turn, payload, owner, cid, *, emit, guard):
        rid = UUID(turn['run_id'])
        async def checked_guard():
            await guard()
            try:
                await self.repository.pulse(owner, cid, rid)
            except ChatError as exc:
                raise GenerationError(exc.code, exc.status) from exc
        async def identified_emit(name, data):
            await emit(name, {**data, 'conversation_id': str(cid), 'run_id': str(rid),
                              'message_id': turn['messages'][1]['id']})
        try:
            answer = await self.generation.execute(payload.query, str(owner), payload.top_k,
                emit=identified_emit, guard=checked_guard, request_id=str(rid),
                history=turn['history'], document_ids=turn['document_ids'], conversation_id=str(cid))
            await checked_guard()
            return await self.repository.finish(owner, cid, rid, answer)
        except asyncio.CancelledError:
            with anyio.CancelScope(shield=True):
                await self._fail(owner, cid, rid, 'cancelled', 'generation_cancelled')
            raise
        except (GenerationError, ChatError) as exc:
            cancelled = exc.code in {'client_disconnected','authorization_lost','generation_cancelled',
                                     'conversation_not_found','account_unavailable'}
            await self._fail(owner, cid, rid, 'cancelled' if cancelled else 'failed', exc.code)
            if isinstance(exc, ChatError): raise GenerationError(exc.code, exc.status) from exc
            raise
        except Exception as exc:
            await self._fail(owner, cid, rid, 'failed', 'generation_unavailable')
            logger.warning('chat_failed error_type=%s', type(exc).__name__)
            raise GenerationError('generation_unavailable', 503, True) from exc

    async def _fail(self, owner, cid, rid, status, code):
        try:
            await asyncio.wait_for(self.repository.fail(owner, cid, rid, status, code), 5)
        except Exception as exc:
            # Lost DB/user/chat: lease expiry recovers the interrupted run.
            logger.warning('chat_terminal_write_failed error_type=%s', type(exc).__name__)
