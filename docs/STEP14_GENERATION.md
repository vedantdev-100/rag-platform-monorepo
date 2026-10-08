# Step 14: hosted generation, LangGraph, SSE and harness

Read this guide before applying. Branch: production-refactor.
Keep services/rag-service and one rag-worker. No new container, schema migration,
local LLM or GPU is introduced. Hosted generation runs inside the API.
This patch was built against your rag_step14_current_source.zip uploaded on 2026-10-08.

## Review findings and scope

Your ZIP is flattened: app/ and service files are at its root; shared packages are
rag-contracts/ and rag-persistence/. The patch maps these back to their real monorepo
paths. It ignores included caches and historical backup files.

Important: the uploaded working files still have the earlier search endpoint,
owner-only repository predicates, unbounded retrieval settings and no
app/rag/retrieval/service.py. Some Step 13 backups exist, but the corresponding active
Step 13 service/helper files do not. This bundle includes those retrieval prerequisite
fixes against the files actually supplied. A preflight mismatch means your live files
are newer/different: send the named files, do not force the patch.

Your actual existing search URL is POST /api/v1/documents/search. It stays unchanged.
The earlier plan's reference to /api/v1/search is corrected here.

Implemented now:
- One standard LangGraph graph: retrieve, bounded context, conditional abstention,
  hosted generation, citation/completion validation.
- Configurable OpenRouter, Groq and OpenAI adapters through Chat Completions HTTP/SSE.
- Normal JSON generation and generation SSE through the same graph.
- Document-status SSE with owner checks, bounded server-side polling and short sessions.
- Rechecks of token expiry/signature/scopes/Redis revocation via the current
  platform-auth v1.0.0 dependency during running requests.
- Deadlines, per-process concurrency caps, bounded queues and disconnect cleanup.
- Optional one-provider fallback, disabled initially; allowed only for transient errors
  before any text has been emitted. No automatic same-provider retry.
- Contract tests, an offline scripted harness and an opt-in live quality/isolation harness.
- API-only generation dependency extra; regenerated uv.lock. Worker excludes LangGraph.

Self-RAG, Corrective RAG and GraphRAG are future extensions, not implemented claims.
There is no persistent chat memory/checkpointer in this step.

## Implementation order

1. Checkpoint your current working branch and review this guide.
2. Run the guarded dry run; apply the prerequisite retrieval fixes and generation files.
3. Install the API generation extra from the supplied lockfile and run the offline harness.
4. Select one provider and one model through API environment settings.
5. Rebuild/recreate API; verify retrieval and existing endpoints still work.
6. Verify normal generation and citations with the included Atlas document.
7. Verify generation SSE and document-status SSE.
8. Run opt-in live quality/isolation checks with real tokens.
9. Keep the accepted lockfile and commit the applied code/configuration examples.

## Files and folder responsibilities

App paths are under services/rag-service.

| Location | Responsibility |
| --- | --- |
| app/rag/generation/settings.py | Independently validated generation settings; worker skips provider requirements |
| app/rag/generation/types.py | Graph state, source and answer contracts, provider/evidence protocols and errors |
| app/rag/generation/providers/openai_compatible.py | Provider URL registry, bounded SSE parser, provider-specific token parameter and optional fallback |
| app/rag/generation/context.py | Versioned initial prompt, prompt-byte budgeting and citation validation |
| app/rag/generation/retrieval_adapter.py | Existing retrieval service with fresh SQL session |
| app/rag/generation/strategies/standard.py | Actual compiled LangGraph graph |
| app/rag/generation/strategies/registry.py | Implemented strategy selection; unknown strategies rejected |
| app/rag/generation/service.py | Graph request lifecycle, capacity, deadline, auth watchdog, public stage callbacks |
| app/rag/generation/events.py | Bounded generation queue and SSE event contract |
| app/rag/generation/auth.py | Reverification through platform-auth; no local JWT validation implementation |
| app/rag/generation/document_status.py | Owner-scoped snapshots and status SSE lifecycle |
| app/schemas/generation.py | Bounded request; rejects extra fields such as owner_id/model/key |
| app/api/v1/endpoints/generation.py | JSON and streaming generation routes |
| app/api/v1/endpoints/document_events.py | Document-status stream route |
| app/api/v1/router.py and app/main.py | Register routes; create/close provider clients at API startup/shutdown |
| app/cli/check_generation.py and check_rag_setup.py | Quality/contract harness and opt-in end-to-end API setup harness |
| app/tests/fixtures/generation_harness.json | Initial known-fact, abstention and adversarial cases |
| app/tests/unit/test_generation*.py, test_document_events.py | Workflow, transport, API, authorization and cleanup checks |
| app/rag/retrieval/*, schemas/search.py, endpoints/search.py, core/config.py | Restore required Step 13 service, validation, limits and provider-result checks |
| packages/rag-persistence/.../chunk_repository.py | Require owner AND ingested status for both retrieval branches |
| pyproject.toml and uv.lock | generation extra: LangGraph 1.2.12 and langchain-core 1.6.6; resolved transitive versions |
| Dockerfile.runtime and app/cli/check_runtime_image.py | API installs/checks LangGraph; worker retains its existing extra |

No new code belongs in external packages/platform-auth. Generation/provider code stays
inside the service. The patch manifest lists every exact changed/added runtime file.

## 1. Apply at the monorepo root, in Git Bash

Extract the delivery ZIP into your repository root. It contains docs/, scripts/ and
refactor/step14/. Code is staged under refactor/step14/patches; extraction does not
replace your application files. Python 3.12 is required for the application script.

```bash
git branch --show-current
git status --short
python --version
python scripts/apply_step14.py --check
python scripts/apply_step14.py
```

Expect production-refactor. Save/commit your current work before applying. The script
checks all originals before any writes, backs up changed existing files to *.step14.bak,
is repeatable, and refuses unexpected local edits. No .env files are changed.

Do not manually copy individual patches over current files if preflight fails.
No Alembic command is required: this step changes no schema.

## 2. Install and run offline checks first

```bash
cd services/rag-service
uv sync --locked --extra generation
uv run --locked --extra generation pytest app/tests/unit/test_generation.py app/tests/unit/test_generation_api.py app/tests/unit/test_generation_auth.py app/tests/unit/test_document_events.py app/tests/unit/test_retrieval_finalization.py app/tests/unit/test_rag_setup_harness.py -q
uv run --locked --extra generation python -m app.cli.check_generation
cd ../..
```

Alternatively, run `bash scripts/run-step14-harness.sh` from the repository root.

The lockfile has already been regenerated. Use --locked so you do not silently resolve
new versions. Both selected framework versions respect your existing seven-day
exclude-newer policy. No full langchain/provider SDK or local model runtime is added.
The default dev group supplies pytest on the host; it is absent in runtime images.

The offline harness uses scripted responses and is a workflow/contract check. It does
not prove model accuracy. The live harness below measures a few initial expected facts
and abstentions; extend its dataset with your real document questions over time.

## 3. Set API environment configuration

Add these to services/rag-service/.env. This file is already used by the rag-service
Compose env_file. Keep existing DB, Redis, embedding, parser, storage and auth settings.
Do not put provider keys into the frontend or commit them. Do not duplicate keys in
root .env.compose: it remains for infrastructure interpolation.

Start with ONE of the provider blocks below. Model IDs are placeholders: replace them
with a currently available model ID from your provider account. No free quota or model
availability is promised. An explicit OpenRouter free model is more repeatable than
openrouter/free, which may select different models.

OpenRouter:
```dotenv
RAG_GENERATION_ENABLED=true
RAG_GENERATION_STRATEGY=standard
RAG_LLM_PROVIDER=openrouter
RAG_LLM_FREE_ONLY=true
OPENROUTER_API_KEY=YOUR_PRIVATE_OPENROUTER_KEY
OPENROUTER_MODEL=YOUR_AVAILABLE_MODEL_ID:free
```

Groq:
```dotenv
RAG_GENERATION_ENABLED=true
RAG_GENERATION_STRATEGY=standard
RAG_LLM_PROVIDER=groq
RAG_LLM_FREE_ONLY=true
GROQ_API_KEY=YOUR_PRIVATE_GROQ_KEY
GROQ_MODEL=YOUR_AVAILABLE_GROQ_MODEL_ID
```

OpenAI, now or later:
```dotenv
RAG_GENERATION_ENABLED=true
RAG_GENERATION_STRATEGY=standard
RAG_LLM_PROVIDER=openai
RAG_LLM_FREE_ONLY=false
OPENAI_API_KEY=YOUR_PRIVATE_OPENAI_KEY
OPENAI_MODEL=YOUR_AVAILABLE_CHAT_COMPLETIONS_MODEL_ID
```

OpenAI requires explicit free-only=false. The OpenAI adapter uses Chat Completions,
not Responses-only models. Model capabilities vary: test the exact model you select.
Providers are selected server-side; requests cannot override keys, owner IDs or URLs.
Secrets use SecretStr and are not returned by the API. Groq free-tier limits are
account-side constraints; the free-only flag cannot guarantee a provider billing plan.

Optional defaults (no need to add all of them unless changing a value):
```dotenv
RAG_LLM_MAX_OUTPUT_TOKENS=512
RAG_LLM_TIMEOUT_SECONDS=90
RAG_LLM_MAX_CONCURRENT=2
RATE_LIMIT_GENERATION=5/minute
RAG_CONTEXT_MAX_BYTES=12000
RAG_CONTEXT_MAX_CHUNKS=5
RAG_SSE_HEARTBEAT_SECONDS=10
RAG_SSE_QUEUE_SIZE=32
RATE_LIMIT_DOCUMENT_EVENTS=10/minute
RAG_DOCUMENT_EVENTS_POLL_SECONDS=3
RAG_DOCUMENT_EVENTS_MAX_SECONDS=300
RAG_DOCUMENT_EVENTS_MAX_CONCURRENT=10
RAG_LLM_FALLBACK_ENABLED=false
```

Optional fallback example: configure both providers' keys/models, then add:
```dotenv
RAG_LLM_FALLBACK_ENABLED=true
RAG_LLM_FALLBACK_PROVIDER=groq
```

The alternate must differ from the primary. Free-only restrictions apply to both.
At most one alternate call is made, only on a transient failure before any text;
there is no same-provider retry or fallback after partial output. Both calls share the
same overall deadline. Leave fallback disabled while checking free-tier behavior.
Successful responses identify the actual provider/model when fallback was used.

RAG_CONTEXT_MAX_BYTES bounds the UTF-8 JSON prompt including instructions/query/source
labels; it is not a token count. RAG_LLM_MAX_OUTPUT_TOKENS bounds the requested provider
completion allowance. Choose limits that fit your model context window; reasoning
models may spend part of their completion allowance on reasoning before visible text.
No reasoning delta fields are sent to the frontend.

The worker uses the same existing service env_file, so it can receive those environment
variables, but it does not use generation or install LangGraph. This step does not
claim secret isolation between containers; separate API/worker env files can be done
later if needed.

If generation is disabled, its routes return 503 generation_disabled and existing
operations continue. Document-status SSE works independently of generation enablement.

## 4. Rebuild and recreate

From the repository root:
```bash
source scripts/dc-step12.sh
dc12 config --quiet
dc12 build rag-service rag-worker
dc12 up -d rag-service rag-worker
dc12 logs --tail=100 rag-service
dc12 exec rag-service python -m app.cli.check_runtime_image --role api --dependencies-only
dc12 exec rag-worker python -m app.cli.check_runtime_image --role worker --dependencies-only
dc12 exec rag-service python -m app.tests.integration.check_container_connections
dc12 exec rag-service python -m app.cli.check_generation
```

Rebuild both once because the shared lockfile changed; LangGraph is selected only by
the API build. Do not rebuild Docling or the embedding model for this step. You still
have exactly one worker. API generation client/graph construction occurs at startup
without making a hosted LLM request.

When only changing the provider/key/model later, recreate the API with
`dc12 up -d --force-recreate rag-service`; no rebuild is needed. Compose env_file values
are captured when a container is created, so a plain restart does not reload them.

Run /health, login, upload, list, status, search and user-deletion checks as before.
Verify the API still releases retrieval DB connections before LLM calls. Keep
PLATFORM_AUTH_REDIS_URL configured so revocation checks are enabled.

## 5. Normal generation in Postman

1. Login and use the same Bearer access token with rag:query scope.
2. Upload docs/fixtures/atlas_generation.txt using the existing POST /api/v1/documents.
3. Wait until GET /api/v1/documents/{id} reports ingested. Save that document ID.
4. POST http://127.0.0.1:8000/api/v1/generation with application/json:

```json
{"query":"Who owns Atlas?","top_k":5}
```

Successful response fields: request_id, status, answer, sources, provider, model, usage.
Expect status=answered, an answer citing [S1] or another supplied label, and source
entries with actual document_id/chunk_id and available pages/headings.
Only cited sources appear in the final response. Stream source previews may contain
additional evidence that the final answer does not cite.

Ask "What is the exact revenue of Atlas?". The fixture does not state revenue: expect
status=insufficient_context and no final sources. Citation checks alone cannot prove
semantic grounding; this is why live evaluations are required.

No usable evidence returns insufficient_context without an LLM call. Retrieved text is
untrusted evidence, delimited as JSON records. The prompt requires factual citations
and abstention. Hybrid/RRF scores are not confidence probabilities.

Common controlled failures:
- 429 generation_busy or provider_rate_limited; honor Retry-After when supplied.
- 503 generation_disabled, provider_configuration_error or provider_unavailable.
- 502 invalid_citations / incomplete_generation; a truncated answer is not success.
- 504 generation_timeout / provider_timeout.

Do not print provider error bodies, token values or full source content in logs.
Logging records request ID, status, duration, provider/model and usage when available;
usage is optional and not a cost estimate. Hosted tracing is not enabled by this setup.

## 6. Generation SSE

POST /api/v1/generation/stream with the same body and Bearer header.
Event contract:

| Event | Payload meaning |
| --- | --- |
| start | request_id |
| stage | retrieving / preparing_context / generating / validating; optional provider_fallback |
| sources | Bounded evidence reference preview |
| delta | Incremental text with provisional=true |
| done | Authoritative final response, validated answer and cited sources |
| error | Sanitized code, retryable/retry_after, discard_provisional=true |

SSE sends provider text chunks, not guaranteed whole words. Text is provisional until
done because complete-answer citation/completion checks happen at the end. Replace
the draft with done.answer. On error, discard it or visibly mark generation as failed;
do not treat a draft with missing/invalid citations as a completed answer.

Use browser fetch with Authorization, a POST body and a streaming reader. Native
EventSource cannot send a POST body or a custom Authorization header. Parse complete
SSE frames across network chunks with a proper parser. Never put the token in a URL.
Use AbortController to cancel when the user navigates away or presses Stop. On the
backend this cancels graph work, closes the upstream response and returns capacity.
No auto-resume/replay is implemented for partial generation.

Heartbeats are comments. Responses disable buffering with X-Accel-Buffering:no and
Cache-Control:no-cache. Any reverse proxy added later must preserve streaming and have
a timeout longer than the application deadline. After HTTP 200 headers are sent,
errors arrive as events, not a changed HTTP status code.

## 7. Document-status SSE

GET /api/v1/documents/{document_id}/events with Bearer authorization. Use streaming fetch
for the frontend's custom authorization header. The stream emits current status,
then changed snapshots, and done when status is ingested or failed. It closes with an
end event at the TTL so the frontend can reconnect if needed.

The successful status remains ingested, not completed. Upload remains HTTP 202/pending.
Status events include generation, retry_count and processed_at. Failure details are
generic, not raw exception traces. Missing or another user's documents return 404.
Deletion during the stream produces a terminal document_not_found error.

This initial implementation uses bounded server-side DB polling every three seconds,
with a fresh session per read. It avoids repeated frontend HTTP polling but does not
eliminate database polling. It has no durable event replay. A reconnect reads the
current snapshot. Move to Redis notifications when actual load justifies it.

Both stream types recheck authentication at intervals (generation: three seconds;
status: each poll) and before successful completion. This bounds revocation response
latency; it does not promise zero-delay invalidation. Data already sent cannot be
retracted. JWT expiry/Redis revocation errors terminate the stream.

## 8. Live harness

The fixture dataset is app/tests/fixtures/generation_harness.json. Start with a test
user whose documents contain only the supplied Atlas fixture for repeatable results.
Upload it and wait for ingested before running. The four cases cover ownership, launch
date, absent revenue and an instruction to fabricate. Change/add cases for real data.

From the repository root in Git Bash, read a token without echoing it:
```bash
read -r -s -p "Test user's access token: " GENERATION_TEST_TOKEN
export GENERATION_TEST_TOKEN
dc12 exec -e GENERATION_TEST_TOKEN rag-service python -m app.cli.check_generation --live --base-url http://127.0.0.1:8000 --expected-document-id YOUR_ATLAS_DOCUMENT_ID
unset GENERATION_TEST_TOKEN
```

This makes four hosted requests and consumes quota. Output contains check results,
latency and usage when available, not tokens or full answers. A failed case exits 1.
It is an initial quality smoke test, not a comprehensive semantic evaluator.

For cross-user isolation, use another user with no documents and set both tokens:
```bash
read -r -s -p "Owner token: " GENERATION_TEST_TOKEN
read -r -s -p "Other user token: " GENERATION_OTHER_USER_TOKEN
export GENERATION_TEST_TOKEN GENERATION_OTHER_USER_TOKEN
dc12 exec -e GENERATION_TEST_TOKEN -e GENERATION_OTHER_USER_TOKEN rag-service python -m app.cli.check_generation --live --base-url http://127.0.0.1:8000 --expected-document-id YOUR_ATLAS_DOCUMENT_ID
unset GENERATION_TEST_TOKEN GENERATION_OTHER_USER_TOKEN
```

Without the second token, isolation is explicitly reported as skipped. Do not call it
a live isolation pass. The ordinary unit suite separately checks SQL owner/status
predicates, graph state separation and document snapshot ownership using offline fixtures.
Repeat live checks for each provider/model you intend to use, with fallback disabled.

For the whole setup, also run the existing container connection/runtime probes above
and verify a fresh upload reaches ingested, search returns that document, both SSE
endpoints complete, and deletion removes DB/MinIO sources. Redis/Docling/ONNX correctness
is covered by those existing integration probes, not an LLM mock alone.

### Entire setup harness (opt-in live)

Use a dedicated account with both rag:ingest and rag:query. This harness creates one
uniquely named test document and makes two hosted LLM requests. It exercises health,
upload, the actual Redis/worker/parser/embedding ingestion path, document status SSE,
persisted status, retrieval, normal generation and generation SSE. It verifies final
SSE done events, an expected fact and the new document's source ID. It does not delete
the account/document automatically. The test document may remain even if a later check
fails; inspect your dedicated account's document list before repeating.

```bash
read -r -s -p "Dedicated test user's access token: " GENERATION_TEST_TOKEN
export GENERATION_TEST_TOKEN
dc12 exec -e GENERATION_TEST_TOKEN rag-service python -m app.cli.check_rag_setup --base-url http://127.0.0.1:8000
unset GENERATION_TEST_TOKEN
```

Use the returned document_id to check the MinIO source checksum/provenance:
```bash
dc12 exec rag-service python -m app.tests.integration.check_document_source RETURNED_DOCUMENT_ID
```

This is an end-to-end smoke harness, alongside the quality dataset harness above.
User-deletion cleanup remains a separate explicit test with a dedicated disposable
account. Do not run legacy ONNX parity or Docling chunking probes in the slim API:
those probes need their original model/worker environments. A real accepted upload
through this harness tests the current remote ingestion path without installing those
dependencies into the API.

## 9. Future strategy boundaries

EvidenceRetriever in types.py is the retrieval contract. GraphState and Answer retain
real source provenance. Extend strategies/registry.py with real implemented builders;
currently only standard is accepted and startup rejects other strategy names.

- Corrective RAG: grade evidence, conditionally rewrite/retrieve again, optionally use
  separately approved external search. Bound total calls/tokens/iterations/deadline.
- Self-RAG-inspired workflow: assess retrieval need, grounding and answer usefulness;
  conditionally revise or abstain. This is not the trained Self-RAG reflection-token model.
- GraphRAG: graph-aware retrieval must return the same evidence/provenance contract.
  Graph construction, summaries, storage/versioning and owner-deletion cleanup are a
  separate ingestion/storage design. Do not add a graph database or second worker now.

Add evaluator protocols and dataset-based regressions when those branches are
implemented. Preserve tenant isolation in graph queries, derived summaries and future
checkpoints. Keep private document evidence distinct from public external-search data.
There is no shared conversation/thread state or user-configurable tool execution now.

Concurrency limits are per API process. Before adding multiple API replicas, introduce
a Redis-backed global capacity/budget coordinator and measure status-poll load. Your
current Redis slowapi rate limiter remains shared; it is not a global concurrency cap.

## 10. Verification and rollback

Local verification completed for this delivery:
- Locked dependencies installed; selected Pydantic/FastAPI/httpx pins retained.
- Offline workflow/provider/API/authorization/document-stream/retrieval tests passed.
- Four scripted harness cases passed.
- Enabled and disabled API lifecycle/import checks passed without hosted calls.
- API dependency boundary passed; worker dependency export excludes LangGraph/core.
- Guarded apply, repeat apply, rollback and mismatch rejection tested on a source copy.

See VERIFICATION.md for exact counts. Docker is unavailable in this execution
environment, so image builds and live PostgreSQL/Redis/MinIO/Docling/embedding/provider
checks remain for your running setup. No hosted key or credential was requested here.

If rolling back, first stop API/worker and restore the patch, then rebuild both from
the restored lockfile:
```bash
source scripts/dc-step12.sh
dc12 stop rag-service rag-worker
python scripts/apply_step14.py --rollback
dc12 build rag-service rag-worker
dc12 up -d rag-service rag-worker
```

The script rejects rollback over subsequent edits rather than delete newer work. It
restores original runtime files/lockfile and removes newly added code. Guide/fixture
files and the staged refactor bundle are not runtime code; keep them for review.
Your .env is untouched; remove or disable generation settings when rolling back.

## Official references

- https://docs.langchain.com/oss/python/langgraph/graph-api
- https://console.groq.com/docs/openai
- https://console.groq.com/docs/rate-limits
- https://openrouter.ai/docs/api/reference/streaming
- https://openrouter.ai/docs/api/reference/limits
- https://developers.openai.com/api/reference/resources/chat

These provider contracts were checked on 2026-10-08. Free models and quotas can change;
select and verify model availability in your provider account.
