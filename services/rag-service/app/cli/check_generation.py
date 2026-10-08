"""Reproducible offline contract harness and opt-in live quality smoke checks.

Live credentials come from GENERATION_TEST_TOKEN / GENERATION_OTHER_USER_TOKEN,
never command-line arguments. Offline outputs are scripted: they validate workflow
contracts, not model quality. Run live checks against the included Atlas document.
"""

import argparse
import asyncio
import json
import os
import time
from pathlib import Path

from app.rag.generation.types import ProviderResult
from app.rag.retrieval.base import RetrievedChunk

DATA = Path(__file__).resolve().parents[1] / "tests/fixtures/generation_harness.json"


def score(case, answer):
    reasons = []
    if answer.get("status") != case["expected_status"]:
        reasons.append("unexpected_status")
    if not all(
        word.lower() in answer.get("answer", "").lower() for word in case["contains"]
    ):
        reasons.append("missing_expected_fact")
    if case["expected_status"] == "answered" and not answer.get("sources"):
        reasons.append("missing_sources")
    if case["expected_status"] == "insufficient_context" and answer.get("sources"):
        reasons.append("abstention_has_sources")
    return reasons


async def offline(data):
    from app.rag.generation.service import GenerationService
    from app.rag.generation.settings import GenerationSettings

    class Evidence:
        async def retrieve(self, query, *, owner_id, top_k):
            return [
                RetrievedChunk(
                    "fixture-chunk", "fixture-document", data["source_text"], 1
                )
            ]

    class Scripted:
        async def generate(self, messages, emit):
            question = (
                messages[1]["content"]
                .split("\nEvidence", 1)[0]
                .removeprefix("Question: ")
            )
            text = next(
                c["mock_answer"] for c in data["cases"] if c["query"] == question
            )
            await emit("delta", {"text": text, "provisional": True})
            return ProviderResult(text=text, finish_reason="stop")

        async def close(self):
            pass

    settings = GenerationSettings(
        _env_file=None,
        RAG_GENERATION_ENABLED=True,
        RAG_RUNTIME_ROLE="development",
        RAG_LLM_PROVIDER="openrouter",
        OPENROUTER_API_KEY="offline",
        OPENROUTER_MODEL="fixture:free",
    )
    service = GenerationService(settings, Evidence(), Scripted())
    reports = []
    for case in data["cases"]:
        start = time.monotonic()
        answer = await service.run(case["query"], "fixture-owner")
        reasons = score(case, answer.model_dump())
        reports.append(
            {
                "case": case["id"],
                "passed": not reasons,
                "failures": reasons,
                "elapsed_ms": int((time.monotonic() - start) * 1000),
            }
        )
    await service.close()
    return reports


async def live(data, base_url, expected_document):
    import httpx

    token = os.environ.get("GENERATION_TEST_TOKEN")
    if not token:
        raise SystemExit(
            "Set GENERATION_TEST_TOKEN to an access token; do not put it on the command line"
        )
    reports = []
    async with httpx.AsyncClient(
        timeout=120, headers={"Authorization": "Bearer " + token}
    ) as client:
        for case in data["cases"]:
            start = time.monotonic()
            response = await client.post(
                base_url.rstrip("/") + "/api/v1/generation",
                json={"query": case["query"]},
            )
            if response.status_code != 200:
                reports.append(
                    {
                        "case": case["id"],
                        "passed": False,
                        "failures": ["http_" + str(response.status_code)],
                    }
                )
                continue
            answer = response.json()
            reasons = score(case, answer)
            if answer["status"] == "answered" and not any(
                s["document_id"] == expected_document for s in answer["sources"]
            ):
                reasons.append("fixture_document_not_cited")
            reports.append(
                {
                    "case": case["id"],
                    "passed": not reasons,
                    "failures": reasons,
                    "elapsed_ms": int((time.monotonic() - start) * 1000),
                    "usage": answer.get("usage"),
                }
            )
        other = os.environ.get("GENERATION_OTHER_USER_TOKEN")
        if other:
            response = await client.post(
                base_url.rstrip("/") + "/api/v1/generation",
                headers={"Authorization": "Bearer " + other},
                json={"query": "Who owns Atlas?"},
            )
            answer = response.json() if response.status_code == 200 else {}
            passed = (
                response.status_code == 200
                and answer.get("status") == "insufficient_context"
                and not answer.get("sources")
            )
            reports.append(
                {
                    "case": "other_owner_isolation",
                    "passed": passed,
                    "failures": [] if passed else ["isolation_check_failed"],
                }
            )
        else:
            reports.append(
                {
                    "case": "other_owner_isolation",
                    "skipped": True,
                    "reason": "Set GENERATION_OTHER_USER_TOKEN for a user with no documents",
                }
            )
    return reports


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--expected-document-id")
    parser.add_argument("--dataset", type=Path, default=DATA)
    args = parser.parse_args()
    if args.live and not args.expected_document_id:
        parser.error(
            "--live requires --expected-document-id for the uploaded Atlas fixture"
        )
    data = json.loads(args.dataset.read_text(encoding="utf-8"))
    reports = asyncio.run(
        live(data, args.base_url, args.expected_document_id)
        if args.live
        else offline(data)
    )
    print(
        json.dumps(
            {
                "mode": "live" if args.live else "offline-scripted-contracts",
                "checks": reports,
            },
            indent=2,
        )
    )
    if any(not c.get("passed", True) for c in reports):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
