# Conversation backend before the React frontend

This overlay extends your working Step 14 backend. Apply it on `production-refactor` before building React. It keeps `rag-service`, your single ingestion worker, external `platform-auth`, existing PostgreSQL/Redis/MinIO/Docling/embedding services, and configurable Groq/OpenRouter/OpenAI providers.

## What is implemented

- Durable, owner-scoped conversations, chat messages and generation runs in the `rag` schema.
- Create/list/reopen/rename/archive/delete chats, with paginated history.
- Selected documents per conversation by default. `all_owner` explicitly searches all of the owner's ingested documents.
- History-aware LangGraph turns: resolve a follow-up question, retrieve scoped evidence, build context, generate, validate, then commit the final message.
- Normal JSON and POST SSE chat endpoints, using the existing generation provider adapters.
- UUID client submission IDs for idempotency; repeated IDs replay an existing result without another provider call. Reusing the same ID with different query/top_k returns 409.
- PostgreSQL owner/conversation row locks, a partial unique active-run index, renewable leases, and final-write fencing. One active turn per conversation across processes; other conversations can run concurrently.
- Pending/completed/failed/cancelled message states, explicit stop, lease-expiry recovery and reloadable run status.
- Authorized citation excerpts and document deletion with the existing durable object-cleanup queue.
- User-deletion cleanup now removes conversations/messages/runs as well as documents. Deactivation still retains data.
- Browser login/refresh/logout with an HttpOnly refresh cookie, exact allowed-Origin checks, and an access-token-only JSON response.
- Refresh refuses missing/inactive accounts and rechecks token consumption under a row lock. Both auth endpoint families inject the existing timestamp-based blacklist so logout revokes access tokens issued before logout.

No provider keys are exposed to the frontend. Existing JSON authentication, generation, document ingestion and retrieval endpoints remain usable.

## Memory design and limits

**Chat thread = conversation UUID.** There is no Python execution thread per chat.

PostgreSQL application tables are the authoritative conversation record. Each turn loads recent *completed* user/assistant pairs. Failed/interrupted pairs are excluded. History is bounded by message count and UTF-8 JSON bytes; previous citation labels are removed from memory. The combined prompt is still bounded by `RAG_CONTEXT_MAX_BYTES`, including history and evidence.

The graph receives a stable `thread_id` for each conversation, but **this overlay does not install a LangGraph checkpointer**. It persists complete turns and run status, not per-node graph snapshots. An API restart preserves chat history; an interrupted generation becomes cancelled after its lease expires and history/run status is read. It is not automatically resumed. Future resumable evaluator/revision loops can add checkpointing with explicit synchronization to message/run IDs.

History is contextual input, never fresh evidence. A follow-up such as “When did she take ownership?” is resolved using earlier turns before retrieval. Facts still need current, authorized document evidence. This is a document-grounded chatbot, so it may abstain on casual questions unsupported by documents.

Follow-ups with history make an additional hosted LLM call to resolve the search question. First turns do not. `answer.usage` records the answer call; `answer.query_resolution_usage` records the resolution call when the provider supplies usage. These consume your provider quota. No paid fallback is introduced.

Summarization, cross-chat personal memory, edit/regenerate branches, automatic mid-stream reconnection/replay, Self-RAG, Corrective RAG and GraphRAG are later extensions. The frontend can start with the contracts below. RAG evaluations can continue separately against the existing generation endpoints.

## Files and migration

Application code changes are staged in `refactor/chat_backend/patches/`. The installer writes them into their actual `services/` and `packages/` locations. `originals/` and the manifest enable guarded source rollback. No application imports this staging folder.

Four new tables:

| Table | Responsibility |
|---|---|
| `rag.conversations` | Owner, title, document scope, archive state and sequence counter |
| `rag.conversation_documents` | Selected document associations |
| `rag.chat_messages` | Ordered user/assistant messages, states and answer/citation snapshots |
| `rag.generation_runs` | Submission ID, request hash, scope snapshot, run status and lease |

New Alembic revision: `b7c42d1f305a`, parent: `a6f31c9e204b`. Existing documents, chunks, embeddings and indexes are retained. No re-ingestion or auth-schema migration is needed. Alembic now imports all RAG models so autogeneration sees the full schema.

This is a source-only update: **no dependency files are changed**. Keep the current Step 14 `uv.lock` from your working checkout. The second uploaded ZIP did not include it, so this delivery does not substitute the older lockfile. Run the locked checks below against your current lockfile; do not remove `--locked`.

## 1. Preflight and apply

Extract the delivery ZIP into the monorepo root, alongside `services`, `packages` and `scripts`. In Git Bash:

```bash
git branch --show-current
git status --short
python scripts/apply-chat-backend.py --check
python scripts/apply-chat-backend.py
```

Expected branch: `production-refactor`. Preserve any local work before application. The installer compares reviewed source content, tolerates CRLF/LF differences, checks every target before changes, and refuses unexpected edits. If it reports a conflict, send the listed files; do not force overwrite them.

Repeat application is safe. The installer does not edit environment files, run migrations, start containers or modify your database.

## 2. Environment settings

In **`services/auth-service/.env`**, for local React development:

```dotenv
ALLOWED_ORIGINS=["http://localhost:5173","http://127.0.0.1:5173"]
AUTH_BROWSER_COOKIE_SECURE=false
AUTH_BROWSER_COOKIE_NAME=rag_refresh
```

In **`services/rag-service/.env`**:

```dotenv
ALLOWED_ORIGINS=["http://localhost:5173","http://127.0.0.1:5173"]
RAG_CHAT_HISTORY_MAX_MESSAGES=12
RAG_CHAT_HISTORY_MAX_BYTES=6000
RAG_CHAT_LEASE_SECONDS=30
RAG_CHAT_MAX_DOCUMENTS=100
RATE_LIMIT_CHAT_MUTATION=30/minute
```

Keep any frontend origins you still use, such as `http://localhost:3000`, in both lists. Do not use `*` for browser sessions. Compose `environment` entries, if added elsewhere, override `env_file` values.

Keep your working provider key/model and `RAG_GENERATION_ENABLED=true`, `RAG_GENERATION_STRATEGY=standard`, `RAG_EMBEDDING_BACKEND=http` and `RAG_PARSER_BACKEND=docling_serve`. Existing `RATE_LIMIT_GENERATION` also applies to both chat generation endpoints.

**Root `.env.compose`: no new required variables.** Preserve current database, Redis, storage and service addresses. The supplied Compose configuration loads both service `.env` files.

For HTTPS deployment, set `AUTH_BROWSER_COOKIE_SECURE=true` and replace CORS origins with your exact frontend origin. The cookie uses SameSite=Lax and a host-only domain; deploy the frontend and auth API on the same site, ideally behind one origin/proxy. A frontend on an unrelated site needs a deliberate cookie/CSRF redesign before deployment.

Use one hostname consistently in local browser requests: frontend `http://localhost:5173`, auth `http://localhost:8001`, RAG `http://localhost:8000`. Do not mix `localhost` and `127.0.0.1` in one browser session.

## 3. Offline checks and image backups

From the repository root:

```bash
bash scripts/run-chat-backend-harness.sh
source scripts/dc-step12.sh
dc12 config --quiet
```

The harness uses mock providers and a dummy DB URL; it does not call providers or your database. It needs host `uv` and Python 3.12 and installs the committed generation/dev environment. Its auth checks execute the relevant reviewed auth functions using test dependencies.

Before rebuilding, tag the currently running images for rollback:

```bash
for chat_service in auth-service rag-service rag-worker; do
  chat_container="$(dc12 ps -q "$chat_service")"
  if [ -z "$chat_container" ]; then
    echo "Missing running container: $chat_service"
    break
  fi
  chat_image="$(docker inspect --format '{{.Image}}' "$chat_container")"
  docker image tag "$chat_image" "rag-chat-backup/$chat_service:before-chat"
done
```

Check that all three tags were created before continuing. Take your normal PostgreSQL backup before the migration.

## 4. Build, drain and migrate

Build while current services are running:

```bash
dc12 build auth-service rag-service rag-worker
```

Stop new ingestion/generation requests. Drain existing ingestion before replacing the worker:

```bash
dc12 stop rag-service
dc12 run --rm --no-deps rag-service python -m app.cli.check_ingestion_drained
```

Keep the old worker running until the drain gate passes. Then:

```bash
dc12 stop rag-worker
dc12 run --rm --no-deps rag-service alembic current
dc12 run --rm --no-deps rag-service alembic heads
```

Before the first chat rollout, current should be `a6f31c9e204b`; heads should be `b7c42d1f305a`. If your database/source has another head, stop and send the output rather than guessing a parent revision. If current is already the new head, skip the upgrade.

```bash
dc12 run --rm --no-deps rag-service alembic upgrade head
dc12 run --rm --no-deps rag-service python -m app.cli.check_chat_repository --concurrency
```

The PostgreSQL probe makes no hosted-provider calls. Its default suite uses temporary records inside a rolled-back transaction. `--concurrency` additionally commits synthetic-owner test records on separate connections, checks concurrent submissions/fencing, then cleans up those records. Use your development database for this gate.

Expected:

```text
Chat PostgreSQL repository acceptance: PASSED (fixtures rolled back)
Chat PostgreSQL concurrent submission and fencing: PASSED
```

No MinIO/embedding/Docling recreation is needed for this step.

## 5. Start the updated services

```bash
dc12 up -d --force-recreate auth-service rag-service rag-worker
dc12 ps
dc12 logs --tail=100 auth-service rag-service rag-worker
dc12 exec rag-service python -m app.cli.check_runtime_image --role api
dc12 exec rag-worker python -m app.cli.check_runtime_image --role worker
```

The worker still excludes LangGraph. Both API and worker need rebuilding because shared RAG persistence and lifecycle cleanup changed.

## 6. Verify browser authentication

The route prefix below assumes your configured `/api/v1`.

Signup remains **POST** `http://localhost:8001/api/v1/auth/register`:

```json
{"email":"your-test-account@example.com","password":"YOUR_TEST_PASSWORD","full_name":"Chat Test"}
```

Browser login: **POST** `http://localhost:8001/api/v1/auth/browser/login`, with JSON:

```json
{"email":"your-test-account@example.com","password":"YOUR_TEST_PASSWORD"}
```

For Postman, add the header `Origin: http://localhost:5173`; its cookie jar must retain `rag_refresh`. Expected: access token, token type and expiry in JSON; refresh token only in the HttpOnly cookie.

Browser refresh: **POST** `/api/v1/auth/browser/refresh`, same Origin header and retained cookie, no JSON body. Expect a new access token and rotated cookie.

Browser logout: **POST** `/api/v1/auth/browser/logout`, same Origin and cookie, no JSON body. Expect 204 and cookie deletion. The old access token should then fail protected calls through the shared blacklist. Re-login creates a token issued after revocation; JWT timestamps have one-second resolution, so allow the next second when testing immediate logout/re-login.

The original `/auth/login`, `/auth/refresh` and `/auth/logout` JSON contracts still work. `/users/me` still uses a Bearer access token.

**React session contract:** use `credentials: "include"` for browser auth calls; keep the access token in memory; restore a session using browser refresh on page load. Serialize refresh attempts with a single shared refresh promise. Do not persist access/refresh tokens in localStorage. RAG calls and source requests carry the access token in `Authorization: Bearer ...`.

The existing auth service still scans bcrypt-hashed refresh tokens. Moving to indexed `token_id.secret` refresh tokens and fully transactional rotation is a later auth-hardening migration; this overlay does not claim that scalability work is complete.

## 7. Conversation and document API

These routes require a Bearer token with `rag:query`, except document upload/deletion which require `rag:ingest`.

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/v1/conversations` | Create chat; default selected-document scope |
| GET | `/api/v1/conversations?limit=20&offset=0&archived=false` | List chats with `has_more` |
| GET | `/api/v1/conversations/{id}` | Chat settings and selected document IDs |
| PATCH | `/api/v1/conversations/{id}` | Rename/archive |
| DELETE | `/api/v1/conversations/{id}` | Delete chat/messages/runs; retain uploaded documents |
| PUT | `/api/v1/conversations/{id}/documents` | Replace document selection and scope |
| GET | `/api/v1/conversations/{id}/messages?limit=50` | Latest page, ascending message sequence |
| GET | `/api/v1/conversations/{id}/messages?limit=50&before=N` | Older history before sequence N |
| POST | `/api/v1/conversations/{id}/messages` | Submit a turn and return committed JSON |
| POST | `/api/v1/conversations/{id}/messages/stream` | Submit a turn and receive SSE |
| GET | `/api/v1/conversations/{id}/runs/{run_id}` | Reload status after interruption/replay |
| POST | `/api/v1/conversations/{id}/runs/{run_id}/cancel` | Stop a running turn; idempotent for terminal runs |
| GET | `/api/v1/documents/{document_id}/chunks/{chunk_id}` | Authorized citation excerpt |
| DELETE | `/api/v1/documents/{document_id}` | Delete ingested/failed document and queue source cleanup |

Create a chat:

```json
{"title":"Atlas discussion","document_scope":"selected"}
```

Upload using existing **POST** `/api/v1/documents`. Then associate its returned document ID:

```json
{"document_scope":"selected","document_ids":["DOCUMENT_UUID"]}
```

`PUT` replaces the selection; the frontend should send the complete desired list. Pending documents can be selected, but retrieval still searches only ingested ones. Continue using the existing document-status SSE or polling before asking about a newly uploaded file. Document association is a separate operation: if it fails, the upload remains in the user's document library and can be attached again.

For all documents:

```json
{"document_scope":"all_owner","document_ids":[]}
```

An empty selected list searches no documents and abstains. Other users' IDs return 404. Scope/title/archive changes during an active turn return 409. Deleting a chat cancels its ability to finish; deleting a document removes its associations, and a turn cannot commit an answer citing a now-unavailable source. Source objects are deleted asynchronously by the existing worker cleanup loop.

Submit a turn, with a **new UUID generated once per logical submission**:

```json
{"query":"Who owns Atlas?","top_k":5,"client_message_id":"CLIENT_UUID"}
```

Reuse that same client ID only when retrying a lost response. A successful result contains `conversation_id`, `run_id`, `client_message_id`, status, and the user/assistant messages. The assistant's `answer` contains the existing status/text/sources/provider/model/usage fields plus optional query-resolution usage.

Then send a new turn:

```json
{"query":"When did she take ownership?","client_message_id":"NEW_CLIENT_UUID"}
```

The backend loads saved history; the frontend does not send owner IDs, arbitrary thread IDs, past assistant messages, provider keys or complete conversation history.

## 8. SSE contract

React should use a streaming `fetch` POST with the Bearer header and an AbortController. Native EventSource does not fit these authenticated POST endpoints. Parse events across network chunk boundaries.

| Event | Frontend behavior |
|---|---|
| `start` | Save conversation/run/user-message/assistant-message IDs |
| `stage` | Show resolving/retrieving/preparing/generating/validating progress |
| `sources` | Show candidate source information |
| `delta` | Append provisional answer text |
| `done` | Replace provisional state with the committed final run/messages/answer |
| `error` | Discard provisional text when instructed; show controlled error; reload run status |
| `replay` | Existing run/result; no new provider call. If running, poll run status |

A `done` event is emitted only after the validated final answer is committed. A connection can still fail after commit but before the client receives done; reload history/run status or repeat the submission ID to discover the committed result. There is no delta-event replay buffer or automatic Last-Event-ID resume.

On Stop, POST the run cancel endpoint and abort the stream. A browser disconnect normally cancels generation and records cancellation. If the process is killed or the database is unavailable, a pending run is recovered after the lease expires and history/status is read. Only completed pairs enter future model history.

## 9. Live HTTP and restart checks

Use a dedicated test account. From repository root:

```bash
uv run --project services/rag-service --locked --extra generation python scripts/check-chat-http.py --isolation
```

It prompts for Bearer tokens without echoing them, uploads a small ownership/date fixture, and verifies ingestion, selected scope, citations, JSON/SSE, follow-up resolution, duplicate submissions, empty scope, and another user's isolation. It leaves the primary fixture/chats for inspection and prints their IDs. It makes hosted LLM calls and uses quota.

Then restart the API:

```bash
dc12 up -d --force-recreate rag-service
```

Reopen the saved chat with GET conversation/history and send a new follow-up. History must survive. Separately test Stop and an interrupted API restart: the assistant placeholder must become cancelled after lease expiry; retrying the same submission ID must not create another answer.

With disposable accounts, verify user deletion through your existing auth flow and confirm all RAG chat tables are purged by the worker. Also repeat existing upload/search/standalone JSON/SSE generation checks. Leave RAG quality evaluations to the parallel workstream.

## 10. Rollback

Source rollback refuses unexpected changes:

```bash
python scripts/apply-chat-backend.py --rollback
```

It retains the migration file, conversation models and lifecycle consumer so the schema revision remains recognized and user-deletion cleanup remains available. It does **not** downgrade PostgreSQL or delete saved chats.

For temporary image rollback, use `docker-compose.chat-rollback.yml` included in this ZIP:

```bash
source scripts/dc-step12.sh
dc12 -f docker-compose.chat-rollback.yml up -d --no-build --force-recreate auth-service rag-service
```

Keep the updated worker running: the pre-chat worker image does not know how to purge chat records. Do not restore the old worker image or rebuild from unreviewed old source while retaining chat data. Reapply the patch to resume chat work.

Do not run `alembic downgrade` merely to restore old endpoints. Dropping the new tables destroys chat history and needs an explicit data-retirement/backup decision.

## Verification performed for this delivery

- 89 offline checks across new chat/auth behavior and existing generation/retrieval/SSE behavior.
- Supplemental ORM execution covering repository ownership, selection, idempotency, history, expiry/fencing and cascade behavior against an in-memory SQLite test adaptation. This does not validate PostgreSQL locks.
- PostgreSQL migration DDL compilation and single-head migration-chain check.
- Installer preflight, repeat application, rollback and unexpected-change refusal.

Docker builds, PostgreSQL migration execution/concurrent-lock checks, browser cookie behavior in your deployment, real provider follow-up quality, and live lifecycle cleanup must run on your machine using the gates above. The full latest lockfile was not supplied; test with your committed lockfile before rollout.

After these gates pass, the React work can implement signup/login, session restore, chat sidebar, document drawer/uploads/status, streamed messages, Stop, pagination and source excerpts using these contracts. No React application is included in this backend delivery.
