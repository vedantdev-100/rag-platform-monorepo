"""Opt-in end-to-end setup harness. Creates ONE test document and makes TWO LLM calls.

Run with a dedicated test account; the document remains for inspection. No automatic
user deletion, model download or infrastructure teardown. Token comes from environment.
"""

import argparse
import asyncio
import json
import os
from pathlib import Path
from uuid import uuid4

import httpx

from app.rag.generation.providers.openai_compatible import sse_events

FIXTURE = Path(__file__).resolve().parents[1] / "tests/fixtures/generation_harness.json"


class CheckFailed(Exception):
    pass


async def require_json(response, status, stage):
    if response.status_code != status:
        raise CheckFailed(stage + "_http_" + str(response.status_code))
    try:
        return response.json()
    except ValueError as exc:
        raise CheckFailed(stage + "_invalid_json") from exc


async def stream_done(client, method, url, **kwargs):
    async with client.stream(method, url, **kwargs) as response:
        if response.status_code != 200:
            raise CheckFailed("stream_http_" + str(response.status_code))
        if "text/event-stream" not in response.headers.get("content-type", ""):
            raise CheckFailed("stream_content_type")
        async for event, raw in sse_events(response.aiter_lines()):
            data = json.loads(raw)
            if "code" in data:
                raise CheckFailed("stream_" + data["code"])
            if data.get("reason") == "stream_ttl":
                raise CheckFailed("document_stream_ttl_reconnect_needed")
            # done generation has answer; done status is ingested/failed.
            if event == "done" and "answer" in data and data.get("status"):
                return data
            if data.get("status") == "failed":
                raise CheckFailed("ingestion_failed")
            if event == "done" and data.get("status") == "ingested":
                return data
    raise CheckFailed("stream_missing_completion")


async def run_setup(client, base_url):
    base = base_url.rstrip("/")
    prefix = base + "/api/v1"
    report = []
    response = await client.get(base + "/health")
    await require_json(response, 200, "health")
    report.append({"stage": "health", "passed": True})
    run_id = "atlas-harness-" + uuid4().hex[:12]
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))["source_text"]
    content = ("Validation run: " + run_id + ".\n" + fixture + "\n").encode()
    response = await client.post(
        prefix + "/documents", files={"file": (run_id + ".txt", content, "text/plain")}
    )
    document = await require_json(response, 202, "upload")
    document_id = document["id"]
    report.append({"stage": "upload", "passed": True, "document_id": document_id})
    # Watches the real Redis -> worker -> parser -> embedding -> persistence path.
    status = await stream_done(
        client, "GET", prefix + "/documents/" + document_id + "/events"
    )
    if status.get("status") != "ingested":
        raise CheckFailed("ingestion_not_complete")
    response = await client.get(prefix + "/documents/" + document_id)
    status = await require_json(response, 200, "document_status")
    if status.get("status") != "ingested":
        raise CheckFailed("status_did_not_persist")
    report.append({"stage": "ingestion_and_status_sse", "passed": True})
    query = "For validation run " + run_id + ", who owns Atlas?"
    response = await client.post(
        prefix + "/documents/search", json={"query": query, "top_k": 5}
    )
    found = await require_json(response, 200, "search")
    if not any(str(s["document_id"]) == document_id for s in found.get("results", [])):
        raise CheckFailed("new_document_not_retrieved")
    report.append({"stage": "retrieval", "passed": True})
    response = await client.post(
        prefix + "/generation", json={"query": query, "top_k": 5}
    )
    answer = await require_json(response, 200, "generation")

    def valid_answer(value):
        return (
            value.get("status") == "answered"
            and "mira" in value.get("answer", "").lower()
            and any(
                str(s["document_id"]) == document_id for s in value.get("sources", [])
            )
        )

    if not valid_answer(answer):
        raise CheckFailed("generation_expected_fact_or_source_missing")
    report.append({"stage": "generation", "passed": True, "usage": answer.get("usage")})
    answer = await stream_done(
        client, "POST", prefix + "/generation/stream", json={"query": query, "top_k": 5}
    )
    if not valid_answer(answer):
        raise CheckFailed("stream_expected_fact_or_source_missing")
    report.append(
        {"stage": "generation_sse", "passed": True, "usage": answer.get("usage")}
    )
    return {
        "passed": True,
        "checks": report,
        "document_id": document_id,
        "note": "Test document retained; use a dedicated test account. Verify MinIO provenance with check_document_source.",
    }


async def live(base_url):
    token = os.environ.get("GENERATION_TEST_TOKEN")
    if not token:
        raise SystemExit(
            "Set GENERATION_TEST_TOKEN for a dedicated test account with rag:ingest and rag:query"
        )
    async with httpx.AsyncClient(
        timeout=330, headers={"Authorization": "Bearer " + token}
    ) as client:
        async with asyncio.timeout(600):
            return await run_setup(client, base_url)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    try:
        print(json.dumps(asyncio.run(live(args.base_url)), indent=2))
    except (CheckFailed, httpx.HTTPError, TimeoutError, ValueError, KeyError) as exc:
        print(
            json.dumps(
                {
                    "passed": False,
                    "failure": str(exc)
                    if isinstance(exc, CheckFailed)
                    else type(exc).__name__,
                }
            )
        )
        raise SystemExit(1)


if __name__ == "__main__":
    main()
