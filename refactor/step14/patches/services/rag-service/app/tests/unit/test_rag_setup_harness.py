import json

import httpx
import pytest

from app.cli.check_rag_setup import CheckFailed, run_setup


@pytest.mark.asyncio
async def test_setup_harness_drives_entire_api_path():
    calls = []
    doc = "test-document"
    answer = {
        "status": "answered",
        "answer": "Mira owns Atlas [S1]",
        "sources": [{"document_id": doc}],
    }

    def handler(request):
        calls.append((request.method, request.url.path))
        assert request.headers["authorization"] == "Bearer private"
        path = request.url.path
        if path.endswith("/health"):
            return httpx.Response(200, json={"status": "ok"})
        if path.endswith("/documents"):
            assert b"Atlas" in request.content
            return httpx.Response(202, json={"id": doc, "status": "pending"})
        if path.endswith("/events"):
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                text='event: done\ndata: {"status":"ingested"}\n\n',
            )
        if path.endswith("/" + doc):
            return httpx.Response(200, json={"status": "ingested"})
        if path.endswith("/search"):
            return httpx.Response(200, json={"results": [{"document_id": doc}]})
        if path.endswith("/generation"):
            return httpx.Response(200, json=answer)
        if path.endswith("/stream"):
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                text="event: done\ndata: " + json.dumps(answer) + "\n\n",
            )
        raise AssertionError(path)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        headers={"Authorization": "Bearer private"},
    ) as client:
        report = await run_setup(client, "http://test")
    assert report["passed"] and len(report["checks"]) == 6 and len(calls) == 7


@pytest.mark.asyncio
async def test_setup_harness_stops_at_failed_upload():
    calls = []

    def handler(request):
        calls.append(request.url.path)
        return (
            httpx.Response(200, json={})
            if request.url.path.endswith("/health")
            else httpx.Response(503)
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(CheckFailed, match="upload_http_503"):
            await run_setup(client, "http://test")
    assert len(calls) == 2
