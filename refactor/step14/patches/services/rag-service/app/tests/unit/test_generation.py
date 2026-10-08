import asyncio
import json

import httpx
import pytest
from pydantic import ValidationError

from app.rag.generation.context import ABSTENTION, build_context, size
from app.rag.generation.events import generation_events
from app.rag.generation.providers.openai_compatible import ChatProvider, sse_data
from app.rag.generation.service import GenerationService, reserve, noop
from app.rag.generation.settings import GenerationSettings
from app.rag.generation.strategies.registry import build_strategy
from app.rag.generation.types import GenerationError, ProviderResult
from app.rag.retrieval.base import RetrievedChunk
from app.schemas.generation import GenerationRequest


def cfg(**kw):
    values = dict(
        RAG_RUNTIME_ROLE="development",
        RAG_GENERATION_ENABLED=True,
        RAG_LLM_PROVIDER="openrouter",
        OPENROUTER_API_KEY="test",
        OPENROUTER_MODEL="example/test:free",
    )
    values.update(kw)
    return GenerationSettings(_env_file=None, **values)


def chunk(text="The project name is Atlas. Its owner is Mira.", owner="a"):
    return RetrievedChunk(
        "chunk-" + owner, "document-" + owner, text, 0.7, metadata={"page": 1}
    )


class Retriever:
    def __init__(self, empty=False):
        self.empty = empty
        self.owners = []

    async def retrieve(self, query, *, owner_id, top_k):
        self.owners.append(owner_id)
        return [] if self.empty else [chunk(owner=owner_id)]


class Provider:
    def __init__(self, text="Atlas is owned by Mira [S1].", reason="stop"):
        self.calls = 0
        self.text, self.reason = text, reason

    async def generate(self, messages, emit):
        self.calls += 1
        await emit("delta", {"text": self.text, "provisional": True})
        return ProviderResult(self.text, {"total_tokens": 20}, self.reason)

    async def close(self):
        pass


@pytest.mark.asyncio
async def test_standard_graph_answer_and_stages():
    events = []

    async def emit(name, data):
        events.append((name, data))

    service = GenerationService(cfg(), Retriever(), Provider())
    answer = await service.run("Who owns Atlas?", "a", emit=emit)
    assert answer.status == "answered" and answer.sources[0].document_id == "document-a"
    assert [d["stage"] for n, d in events if n == "stage"] == [
        "retrieving",
        "preparing_context",
        "generating",
        "validating",
    ]
    assert all(d["request_id"] == answer.request_id for n, d in events)


@pytest.mark.asyncio
async def test_empty_evidence_skips_provider():
    provider = Provider()
    result = await GenerationService(cfg(), Retriever(empty=True), provider).run(
        "query", "a"
    )
    assert result.status == "insufficient_context" and provider.calls == 0


@pytest.mark.asyncio
async def test_provider_abstention():
    result = await GenerationService(cfg(), Retriever(), Provider(ABSTENTION)).run(
        "unknown", "a"
    )
    assert result.status == "insufficient_context" and result.sources == []


@pytest.mark.parametrize(
    "text,reason,code",
    [
        ("invented [S9]", "stop", "invalid_citations"),
        ("no citation", "stop", "invalid_citations"),
        ("", "stop", "empty_generation"),
        ("text [S1]", "length", "incomplete_generation"),
        ("text [S1]", "content_filter", "incomplete_generation"),
    ],
)
@pytest.mark.asyncio
async def test_invalid_outputs_fail(text, reason, code):
    with pytest.raises(GenerationError, match=code):
        await GenerationService(cfg(), Retriever(), Provider(text, reason)).run(
            "q", "a"
        )


def test_context_is_bounded_for_unicode_and_escaping():
    settings = cfg(RAG_CONTEXT_MAX_BYTES=2000)
    messages, sources = build_context("q", [chunk('🌍"\\\n' * 5000)], settings)
    assert size(messages) <= 2000 and len(sources) == 1
    record = json.loads(messages[1]["content"].split("Evidence (JSON records):\n")[1])
    assert record["text"] and record["label"] == "S1"


def test_duplicate_and_empty_chunks():
    _, sources = build_context("q", [chunk(""), chunk(), chunk()], cfg())
    assert len(sources) == 1


@pytest.mark.parametrize(
    "body",
    [
        {"query": " "},
        {"query": "q", "top_k": True},
        {"query": "q", "top_k": 51},
        {"query": "q", "owner_id": "a"},
    ],
)
def test_request_bounds(body):
    with pytest.raises(ValidationError):
        GenerationRequest(**body)


def test_free_model_and_openai_configuration():
    with pytest.raises(ValidationError):
        GenerationSettings(
            _env_file=None,
            RAG_GENERATION_ENABLED=True,
            OPENROUTER_API_KEY="test",
            OPENROUTER_MODEL="paid/model",
        )
    settings = GenerationSettings(
        _env_file=None,
        RAG_GENERATION_ENABLED=True,
        RAG_LLM_PROVIDER="openai",
        OPENAI_API_KEY="test",
        OPENAI_MODEL="chosen-model",
        RAG_LLM_FREE_ONLY=False,
    )
    assert settings.model == "chosen-model"
    worker = GenerationSettings(
        _env_file=None, RAG_GENERATION_ENABLED=True, RAG_RUNTIME_ROLE="worker"
    )
    assert not worker.active


def test_future_strategy_rejected():
    with pytest.raises(ValueError, match="not been implemented"):
        build_strategy("self_rag", cfg(), Retriever(), Provider())


@pytest.mark.asyncio
async def test_requests_do_not_share_state():
    retriever = Retriever()
    service = GenerationService(cfg(), retriever, Provider())
    a, b = await asyncio.gather(service.run("q", "a"), service.run("q", "b"))
    assert a.request_id != b.request_id
    assert a.sources[0].document_id != b.sources[0].document_id


@pytest.mark.asyncio
async def test_capacity_released_after_failure():
    service = GenerationService(
        cfg(RAG_LLM_MAX_CONCURRENT=1), Retriever(), Provider("bad")
    )
    with pytest.raises(GenerationError):
        await service.run("q", "a")
    lease = await reserve(service.capacity)
    with pytest.raises(GenerationError, match="generation_busy"):
        await reserve(service.capacity)
    await lease.release()
    await lease.release()
    assert service.capacity._value == 1


@pytest.mark.asyncio
async def test_sse_validation_error_discards_draft():
    service = GenerationService(cfg(), Retriever(), Provider("invented [S9]"))
    lease = await reserve(service.capacity)
    events = [
        e async for e in generation_events(service, lease, "q", "a", None, noop, "req")
    ]
    assert '"discard_provisional": true' in events[-1] and "event: error" in events[-1]
    assert not any("event: done" in e for e in events)
    assert lease.released


@pytest.mark.asyncio
async def test_sse_success():
    service = GenerationService(cfg(), Retriever(), Provider())
    lease = await reserve(service.capacity)
    events = [
        e async for e in generation_events(service, lease, "q", "a", None, noop, "req")
    ]
    assert "event: done" in events[-1] and lease.released


@pytest.mark.asyncio
async def test_sse_close_cancels_upstream_and_releases_lease():
    started, stopped = asyncio.Event(), asyncio.Event()

    class Blocking(Provider):
        async def generate(self, messages, emit):
            started.set()
            try:
                while True:
                    await emit("delta", {"text": "x"})
            finally:
                stopped.set()

    service = GenerationService(cfg(RAG_SSE_QUEUE_SIZE=1), Retriever(), Blocking())
    lease = await reserve(service.capacity)
    stream = generation_events(service, lease, "q", "a", None, noop, "req")
    await anext(stream)
    while not started.is_set():
        await anext(stream)
    await stream.aclose()
    assert stopped.is_set() and lease.released


@pytest.mark.asyncio
async def test_deadline_cancels_provider():
    stopped = asyncio.Event()

    class Blocking(Provider):
        async def generate(self, messages, emit):
            try:
                await asyncio.Event().wait()
            finally:
                stopped.set()

    settings = cfg()
    settings.RAG_LLM_TIMEOUT_SECONDS = (
        0.02  # Only shorten test deadline, not validated production config.
    )
    service = GenerationService(settings, Retriever(), Blocking())
    with pytest.raises(GenerationError, match="generation_timeout"):
        await service.run("q", "a")
    assert stopped.is_set() and service.capacity._value == 2


@pytest.mark.asyncio
async def test_authorization_guard_prevents_answer():
    calls = 0

    async def guard():
        nonlocal calls
        calls += 1
        if calls >= 2:
            raise GenerationError("authorization_lost", 401)

    with pytest.raises(GenerationError, match="authorization_lost"):
        await GenerationService(cfg(), Retriever(), Provider()).run(
            "q", "a", guard=guard
        )


def wire(*frames):
    return "".join(
        "data: " + (f if isinstance(f, str) else json.dumps(f)) + "\n\n" for f in frames
    )


def frame(text="", reason=None):
    return {"choices": [{"delta": {"content": text}, "finish_reason": reason}]}


@pytest.mark.parametrize("provider", ["openrouter", "groq", "openai"])
@pytest.mark.asyncio
async def test_provider_protocols(provider):
    data = ": heartbeat\n\n" + wire(
        frame("Mira [S1]"),
        frame(reason="stop"),
        {"choices": [], "usage": {"total_tokens": 12}},
        "[DONE]",
    )
    requests = []

    async def handler(request):
        requests.append(request)
        return httpx.Response(
            200, headers={"content-type": "text/event-stream"}, text=data
        )

    kw = {
        "RAG_LLM_PROVIDER": provider,
        provider.upper() + "_MODEL": "test:free",
        provider.upper() + "_API_KEY": "test",
        "RAG_LLM_FREE_ONLY": False,
    }
    settings = GenerationSettings(_env_file=None, RAG_GENERATION_ENABLED=True, **kw)
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    llm = ChatProvider(settings, client)
    result = await llm.generate([], noop)
    assert result.text == "Mira [S1]" and result.usage["total_tokens"] == 12
    body = json.loads(requests[0].content)
    key = "max_tokens" if provider == "openrouter" else "max_completion_tokens"
    assert key in body and body["stream"]
    await llm.close()


@pytest.mark.parametrize(
    "data,code",
    [
        (wire(frame("x")), "incomplete_generation"),
        (
            wire({"error": {"message": "secret provider details"}}),
            "invalid_provider_stream",
        ),
        ("data: {bad}\n\n", "invalid_provider_stream"),
        (wire(frame("x", "stop"), frame(reason="length")), "invalid_provider_stream"),
    ],
)
@pytest.mark.asyncio
async def test_provider_errors_are_sanitized(data, code):
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(
                200, headers={"content-type": "text/event-stream"}, text=data
            )
        )
    )
    llm = ChatProvider(cfg(), client)
    with pytest.raises(GenerationError, match=code) as e:
        await llm.generate([], noop)
    assert "secret" not in str(e.value)
    await llm.close()


@pytest.mark.parametrize(
    "status,code",
    [
        (401, "provider_configuration_error"),
        (429, "provider_rate_limited"),
        (500, "provider_unavailable"),
    ],
)
@pytest.mark.asyncio
async def test_provider_http_errors(status, code):
    attempts = []

    def handler(request):
        attempts.append(request)
        return httpx.Response(status, headers={"retry-after": "7"}, text="secret")

    llm = ChatProvider(cfg(), httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    with pytest.raises(GenerationError, match=code) as e:
        await llm.generate([], noop)
    assert len(attempts) == 1 and e.value.retry_after == 7
    await llm.close()


@pytest.mark.asyncio
async def test_sse_multiline_and_frame_bounds():
    async def lines():
        for line in [": comment", "data: first", "data: second", "", "data: tail"]:
            yield line

    assert [d async for d in sse_data(lines())] == ["first\nsecond", "tail"]
    with pytest.raises(GenerationError, match="frame_too_large"):
        [d async for d in sse_data(lines(), max_frame=3)]


@pytest.mark.asyncio
async def test_optional_fallback_only_before_text():
    from app.rag.generation.providers.openai_compatible import FallbackProvider

    class Failed(Provider):
        async def generate(self, messages, emit):
            raise GenerationError("provider_rate_limited", 429, True)

    alternate = Provider()
    alternate.settings = cfg()
    fallback = FallbackProvider(Failed(), alternate)
    result = await fallback.generate([], noop)
    assert alternate.calls == 1 and result.finish_reason == "stop"

    class Partial(Provider):
        async def generate(self, messages, emit):
            await emit("delta", {"text": "partial"})
            raise GenerationError("provider_unavailable", 503, True)

    alternate.calls = 0
    with pytest.raises(GenerationError):
        await FallbackProvider(Partial(), alternate).generate([], noop)
    assert alternate.calls == 0


def test_fallback_configuration_validated():
    with pytest.raises(ValidationError):
        cfg(
            RAG_LLM_FALLBACK_ENABLED=True,
            RAG_LLM_FALLBACK_PROVIDER="openai",
            OPENAI_API_KEY="test",
            OPENAI_MODEL="model",
        )
    settings = cfg(
        RAG_LLM_FALLBACK_ENABLED=True,
        RAG_LLM_FALLBACK_PROVIDER="groq",
        GROQ_API_KEY="test",
        GROQ_MODEL="model",
    )
    assert settings.RAG_LLM_FALLBACK_ENABLED


@pytest.mark.asyncio
async def test_provider_utf8_boundaries_and_repeated_finish():
    data = wire(frame("Mira 🌍 [S1]", "stop"), frame(reason="stop"), "[DONE]").encode()

    class Bytes(httpx.AsyncByteStream):
        async def __aiter__(self):
            for i in range(0, len(data), 3):
                yield data[i : i + 3]

        async def aclose(self):
            pass

    llm = ChatProvider(
        cfg(),
        httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda r: httpx.Response(
                    200, headers={"content-type": "text/event-stream"}, stream=Bytes()
                )
            )
        ),
    )
    result = await llm.generate([], noop)
    assert result.text == "Mira 🌍 [S1]"
    await llm.close()


@pytest.mark.asyncio
async def test_auth_failure_does_not_drain_buffered_evidence():
    calls = 0

    async def guard():
        nonlocal calls
        calls += 1
        if calls >= 2:
            raise GenerationError("authorization_lost", 401)

    service = GenerationService(cfg(), Retriever(), Provider())
    lease = await reserve(service.capacity)
    events = [
        e async for e in generation_events(service, lease, "q", "a", None, guard, "req")
    ]
    assert "authorization_lost" in events[-1]
    assert not any("event: done" in e for e in events)
    assert lease.released


@pytest.mark.asyncio
async def test_provider_cancellation_closes_http_response():
    emitted, closed = asyncio.Event(), asyncio.Event()

    class BlockingBytes(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield wire(frame("draft")).encode()
            await asyncio.Event().wait()

        async def aclose(self):
            closed.set()

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                stream=BlockingBytes(),
            )
        )
    )
    provider = ChatProvider(cfg(), client)

    async def emit(*a):
        emitted.set()

    task = asyncio.create_task(provider.generate([], emit))
    await asyncio.wait_for(emitted.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert closed.is_set()
    await provider.close()
