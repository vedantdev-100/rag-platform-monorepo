import asyncio

import httpx
import pytest
from fastapi import FastAPI
from platform_auth import AuthenticatedUser

from app.api.v1.endpoints import generation, document_events
from app.rag.generation.service import GenerationService
from app.rag.generation.types import GenerationError
from app.tests.unit.test_generation import cfg, Retriever, Provider


@pytest.fixture
def api(monkeypatch):
    app = FastAPI()
    app.include_router(generation.router, prefix="/api/v1")
    app.include_router(document_events.router, prefix="/api/v1")
    # Exact current require_scopes dependencies, with transport/auth mocks only.
    for route in app.routes:
        dep = getattr(route, "dependant", None)
        if dep:
            for first in dep.dependencies:
                for child in first.dependencies:
                    app.dependency_overrides[child.call] = lambda: AuthenticatedUser(
                        id="a", role="user", scopes=["rag:query"]
                    )

    async def guard():
        pass

    monkeypatch.setattr(generation, "authorization_guard", lambda *a: guard)
    monkeypatch.setattr(document_events, "authorization_guard", lambda *a: guard)
    generation.limiter.enabled = False
    document_events.limiter.enabled = False
    app.state.generation_service = GenerationService(cfg(), Retriever(), Provider())
    yield app
    generation.limiter.enabled = True


@pytest.mark.asyncio
async def test_normal_and_stream_api(api):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=api), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/generation", json={"query": "Who owns Atlas?"}
        )
        assert response.status_code == 200 and response.json()["status"] == "answered"
        response = await client.post(
            "/api/v1/generation/stream", json={"query": "Who owns Atlas?"}
        )
        assert (
            response.status_code == 200
            and "text/event-stream" in response.headers["content-type"]
        )
        assert "event: done" in response.text and "event: delta" in response.text
        assert api.state.generation_service.capacity._value == 2


@pytest.mark.asyncio
async def test_disabled_and_validation_api(api):
    api.state.generation_service = None
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=api), base_url="http://test"
    ) as client:
        response = await client.post("/api/v1/generation", json={"query": "q"})
        assert response.status_code == 503
        response = await client.post(
            "/api/v1/generation", json={"query": "q", "owner_id": "other"}
        )
        assert response.status_code == 422


@pytest.mark.asyncio
async def test_doc_not_found_before_stream(api, monkeypatch):
    async def missing(*a):
        raise GenerationError("document_not_found", 404)

    monkeypatch.setattr(document_events, "snapshot", missing)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=api), base_url="http://test"
    ) as client:
        response = await client.get(
            "/api/v1/documents/00000000-0000-0000-0000-000000000001/events"
        )
        assert (
            response.status_code == 404
            and api.state.document_events_capacity._value == 10
        )


@pytest.mark.asyncio
async def test_asgi_disconnect_cancels_generation(api):
    started, stopped = asyncio.Event(), asyncio.Event()

    class Blocking(Provider):
        async def generate(self, messages, emit):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                stopped.set()

    api.state.generation_service = GenerationService(
        cfg(RAG_LLM_MAX_CONCURRENT=1), Retriever(), Blocking()
    )
    body = b'{"query":"q"}'
    first = True
    disconnect = asyncio.Event()

    async def receive():
        nonlocal first
        if first:
            first = False
            return {"type": "http.request", "body": body, "more_body": False}
        await disconnect.wait()
        return {"type": "http.disconnect"}

    async def send(message):
        if message["type"] == "http.response.body":
            if started.is_set():
                disconnect.set()

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/v1/generation/stream",
        "raw_path": b"/api/v1/generation/stream",
        "query_string": b"",
        "headers": [(b"content-type", b"application/json")],
        "client": ("127.0.0.1", 123),
        "server": ("test", 80),
        "root_path": "",
    }
    task = asyncio.create_task(api(scope, receive, send))
    await asyncio.wait_for(started.wait(), 2)
    disconnect.set()
    await asyncio.wait_for(task, 2)
    assert stopped.is_set() and api.state.generation_service.capacity._value == 1
