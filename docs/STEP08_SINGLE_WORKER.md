# Step 8 — move lifecycle and cleanup into one rag-worker container

Step 7 is verified: uploads work, and deleting a user removes their RAG rows and MinIO objects. This step gives background work its own process before introducing asynchronous ingestion.

## Intended behavior

| Process | After Step 8 |
| --- | --- |
| `rag-service` | HTTP endpoints, synchronous ingestion, search and retrieval |
| `rag-worker` | Existing user lifecycle consumer and durable source-cleanup loop |
| Auth / PostgreSQL / Redis / MinIO | Same credentials, schemas, streams, groups and volumes |

One worker container runs both existing loops. The API disables them through `RUN_LIFECYCLE_CONSUMER=false`. The worker uses the existing `user-events` stream and `rag-service` consumer group; do not rename either during handoff.

The worker reuses `rag-platform/rag-service:local` with command `python -m app.worker`. This avoids a separate image/dependency build during extraction. The process imports configuration, persistence, lifecycle and storage code; it starts no HTTP server and imports no parser/embedding model factories. The shared image still contains the current ML dependencies, so its disk size has not yet been reduced. It does not need a model-directory mount.

## Exact files

| Path relative to repository root | Action |
| --- | --- |
| `services/rag-service/app/worker.py` | New process entry point with signal handling |
| `docker-compose.worker.yml` | New third Compose overlay |
| `scripts/apply_step08_runtime.py` | New; adds a settings flag and guards the existing API consumer hooks |
| `scripts/dc.sh` | New; defines the updated Compose shortcut |
| `docs/STEP08_SINGLE_WORKER.md` | New; these instructions |
| `services/rag-service/app/core/config.py` | Patched by the script, preserving other fields |
| `services/rag-service/app/main.py` | Patched by the script, preserving routes/middleware/auth |

Keep the Step 7 storage, pipeline and consumer implementations. No migration, dependency or API-response changes are needed. Branch stays `production-refactor`; the API directory stays `services/rag-service`.

## 1. Apply and inspect the runtime patch

Extract the ZIP into the repository root. In Git Bash there:

```bash
git branch --show-current
python scripts/apply_step08_runtime.py
git diff -- services/rag-service/app/core/config.py services/rag-service/app/main.py
source scripts/dc.sh
dc config --quiet
```

Expected config addition: `RUN_LIFECYCLE_CONSUMER: bool = True`. The default retains host development behavior, while Compose explicitly disables the API consumer and enables the worker.

The main patch guards only the supplied consumer creation and startup/shutdown hooks. Shutdown now cancels and awaits its task before closing Redis. Routes, authentication and middleware remain in place. If your current hooks differ, the script stops without writing either file; supply your current `main.py` for a tailored patch. Do not replace the whole file to bypass that check.

**Replace the earlier dc shortcut.** It must now load all three files, in order:

1. `docker-compose.yml`
2. `docker-compose.minio.yml`
3. `docker-compose.worker.yml`

In each new terminal, run `source scripts/dc.sh` from the root. Running only the earlier two-file configuration would re-enable background consumption in the API while the worker remains running.

## 2. Build and hand off without overlapping consumers

```bash
dc build rag-service
dc stop rag-service
dc up -d --force-recreate minio-init
dc up -d --force-recreate rag-service rag-worker
dc ps
dc logs --tail=100 rag-service rag-worker
```

Stop any host-run RAG process as well. The existing Redis stream buffers events during the short handoff.

Expected API log: `api_background_consumers_disabled`.

Expected worker logs: `rag_worker_started` and `user_event_consumer_started`. The worker has no published port or HTTP health endpoint; an Up status indicates the process is running, and the next checks prove its behavior. Connection failures appear in its logs and are retried by the existing loops.

The worker's restart policy is `unless-stopped`. Graceful stop allows up to 120 seconds for bounded storage operations. Interrupted cleanup claims remain in the outbox and become eligible again after their three-minute lease expires.

## 3. Verify ownership of the loops

```bash
dc exec rag-service python -c "from app.core.config import get_settings; print(get_settings().RUN_LIFECYCLE_CONSUMER)"
dc exec rag-worker python -c "from app.core.config import get_settings; print(get_settings().RUN_LIFECYCLE_CONSUMER)"
```

Expected: API `False`, worker `True`.

Log in, list/retrieve/search existing documents and upload a new one. Upload still returns 201 only after ingestion completes. Use the Step 7 source check on its returned UUID:

```bash
dc exec rag-service python -m app.tests.integration.check_document_source YOUR_DOCUMENT_UUID
```

## 4. Verify worker deletion and catch-up

With a disposable Auth test account:

1. Upload one document and note its document UUID and MinIO object key.
2. Delete that account through Auth.
3. Confirm the worker logs `user_deleted_documents_purged` and then `source_cleanup_completed`.
4. Confirm the source object and the account's RAG document rows are removed, as you did in Step 7.

Then verify catch-up with a second disposable account:

```bash
dc stop rag-worker
```

Upload one document while the worker is stopped; ingestion still works in the API. Delete that disposable account through Auth. Its source and RAG rows should remain until the worker resumes; the API no longer performs lifecycle cleanup.

```bash
dc start rag-worker
dc logs --tail=100 rag-worker
```

Confirm the queued lifecycle event is processed and both the source and rows disappear. Keep using test accounts, not accounts with data you want to retain.

If you rerun `check_source_cleanup` from Step 7, stop `rag-worker` first to avoid racing its cleanup loop, then restart it afterward. Stopping only `rag-service` no longer stops background cleanup.

## Completion, rollback and next steps

Step 8 is complete when API flag is False, worker flag is True, normal endpoints work, worker-driven deletion works, and deletion catches up after a worker stop/start.

To return background work temporarily to the API while retaining the new code:

1. Stop `rag-worker`.
2. Remove only `-f docker-compose.worker.yml` from the shortcut.
3. Recreate `rag-service` with the original two overlays; its default flag is True.

Never run that fallback alongside an active worker. Keep MinIO and its volume; no data migration or image downgrade is needed.

Step 9 will add durable ingestion jobs and move parsing/chunking/embedding orchestration into this same worker. It will introduce upload acceptance (202), polling for document status, job identity, retries, leases, duplicate-delivery protection and source reservation/reconciliation. Subsequent steps connect Docling Serve and BGE ONNX, then remove the heavy ML dependencies from the API image. No second worker is planned.

## Validation

The settings/main patch was checked against your uploaded main file with Step 7 settings applied, including repeat execution and preservation of route-registration code. Worker Python syntax, shutdown orchestration and Compose structure were checked. Docker is unavailable in the authoring environment, so the handoff, signal handling and actual lifecycle/cleanup behavior must be verified on your machine with the steps above.
