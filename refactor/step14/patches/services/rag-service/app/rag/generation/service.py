import asyncio
import logging
import time
from uuid import uuid4

from app.rag.generation.types import GenerationError
from app.rag.generation.strategies.registry import build_strategy
from app.rag.retrieval.validation import normalize_query

logger = logging.getLogger(__name__)


class Lease:
    def __init__(self, semaphore):
        self.semaphore, self.released = semaphore, False

    async def release(self):
        if not self.released:
            self.released = True
            self.semaphore.release()


async def reserve(semaphore, code="generation_busy"):
    try:
        await asyncio.wait_for(semaphore.acquire(), timeout=0.05)
    except TimeoutError as exc:
        raise GenerationError(code, 429, True, 2) from exc
    return Lease(semaphore)


async def noop(*args):
    pass


class GenerationService:
    def __init__(self, settings, retriever, provider):
        self.settings, self.provider = settings, provider
        self.capacity = asyncio.Semaphore(settings.RAG_LLM_MAX_CONCURRENT)
        self.graph = build_strategy(
            settings.RAG_GENERATION_STRATEGY, settings, retriever, provider
        )

    async def close(self):
        await self.provider.close()

    async def execute(
        self, query, owner_id, top_k=None, *, emit=noop, guard=noop, request_id=None
    ):
        started = time.monotonic()
        request_id = request_id or str(uuid4())

        async def checked_emit(name, data):
            await emit(name, {"request_id": request_id, **data})

        async def work():
            await guard()
            async with asyncio.timeout(self.settings.RAG_LLM_TIMEOUT_SECONDS):
                state = await self.graph.ainvoke(
                    {
                        "query": normalize_query(query),
                        "owner_id": owner_id,
                        "top_k": top_k,
                        "request_id": request_id,
                    },
                    config={
                        "configurable": {"emit": checked_emit},
                        "recursion_limit": 12,
                    },
                )
                await guard()
                return state["answer"]

        async def monitor():
            while True:
                await asyncio.sleep(3)
                await guard()

        task, watchdog = asyncio.create_task(work()), asyncio.create_task(monitor())
        status = "error"
        try:
            done, _ = await asyncio.wait(
                {task, watchdog}, return_when=asyncio.FIRST_COMPLETED
            )
            if watchdog in done:
                await watchdog
                raise GenerationError("authorization_lost", 401)
            answer = await task
            status = answer.status
            logger.info(
                "generation_done request_id=%s status=%s provider=%s model=%s usage=%s",
                request_id,
                status,
                answer.provider,
                answer.model,
                answer.usage,
            )
            return answer
        except TimeoutError as exc:
            raise GenerationError("generation_timeout", 504, True) from exc
        except GenerationError:
            raise
        except asyncio.CancelledError:
            status = "cancelled"
            raise
        except Exception as exc:
            # Never send provider bodies/prompts or exception text to the client/log.
            logger.warning(
                "generation_failed request_id=%s error_type=%s",
                request_id,
                type(exc).__name__,
            )
            raise GenerationError("generation_unavailable", 503, True) from exc
        finally:
            task.cancel()
            watchdog.cancel()
            await asyncio.gather(task, watchdog, return_exceptions=True)
            logger.info(
                "generation_finished request_id=%s status=%s elapsed_ms=%d",
                request_id,
                status,
                int((time.monotonic() - started) * 1000),
            )

    async def run(self, *args, **kwargs):
        lease = await reserve(self.capacity)
        try:
            return await self.execute(*args, **kwargs)
        finally:
            await lease.release()
