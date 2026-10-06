# Step 7 — MinIO source storage

Apply on `production-refactor`, after Step 6 endpoints work in Docker. This overlay is based on your freshly uploaded pipeline, factory, consumer, storage and document endpoints. The UUID normalization, vector validation and short ingestion transactions are retained. Upload remains synchronous and returns 201 on success.

## Result and implementation order

1. Add an S3-compatible MinIO adapter behind the existing `FileStorage` interface. New object URIs are `s3://rag-documents/raw/<random-UUID>.<extension>`. Filenames remain document titles; duplicate filenames do not overwrite objects.
2. Route reads/deletes by the stored URI, so local documents remain usable after new uploads switch to MinIO. Keep the existing local upload bind mount.
3. Save object location, SHA-256 checksum, byte count and inferred MIME type on new document rows, using Step 5 fields. Record embedding dimension and completion time on success.
4. On failed source writes or failed initial DB creation, record an independent cleanup intent. The cleanup executor checks for a persisted document reference before deleting, covering an ambiguous commit response. Storage write failures return HTTP 503. Parsing/embedding failures retain their failed document and raw source for a future retry.
5. For `user.deleted`, lock the owner's lifecycle state, record a deletion tombstone, queue source cleanup and delete DB documents in one transaction. Final ingestion commits take the same owner lock. Deactivation/reactivation do not delete sources or undo deletion tombstones.
6. Execute source cleanup through an independent async loop in the existing API process. Failed deletion uses capped backoff; expired claims are retried after restart. This loop will move to the single worker at queue cutover. Lifecycle pending-message recovery now uses Redis XAUTOCLAIM (Redis 6.2+).

There is no new worker container in this step. PostgreSQL, Redis, the embedding implementation and parser remain as they were.

## Files to apply

| Relative path | Action |
| --- | --- |
| `docker-compose.minio.yml` | New overlay; keep existing `docker-compose.yml` |
| `infra/minio/Dockerfile` | New source-built MinIO image |
| `scripts/apply_step07_config.py` | New; adds only the storage settings to your config |
| `app/rag/ingestion/storage.py` | Replace under `services/rag-service` |
| `app/rag/ingestion/storage_factory.py` | New, independent of model-loading factories |
| `app/rag/ingestion/factory.py` | Replace with your supplied version plus storage selection |
| `app/rag/ingestion/pipeline.py` | Replace with your supplied version plus provenance/cleanup/fencing |
| `app/events/source_cleanup.py` | New cleanup intent and executor functions |
| `app/events/consumer.py` | Replace with durable source cleanup and pending recovery |
| `app/api/v1/endpoints/documents.py` | Replace with your supplied version plus storage-error mapping |
| `app/cli/init_minio.py` | New private bucket initializer |
| `app/tests/unit/test_source_storage.py` | New deterministic storage tests |
| `app/tests/integration/check_source_storage.py` | New actual backend round-trip check |
| `app/tests/integration/check_source_cleanup.py` | New actual DB/storage cleanup check |
| `app/tests/integration/check_document_source.py` | New check for a newly uploaded document |
| `docs/step07_env_additions.env` | Values to append to root `.env.compose` |

Keep `base.py`: its save/read/delete interface does not change. Keep the Step 6 connection-check fixes. No shared-package model changes or new Alembic revision are required. Keep `services/rag-service/Dockerfile` and the Auth service as they are.

## 1. Apply, add settings and lock the dependency

Extract into the repository root. From that root:

```bash
git branch --show-current
python scripts/apply_step07_config.py
cd services/rag-service
uv add 'boto3==1.40.20'
uv sync --locked
uv run python -m unittest app.tests.unit.test_source_storage -v
cd ../..
```

The config script replaces only `STORAGE_BACKEND: Literal["local"] = "local"` with the new settings and validator, retaining all other settings. It stops if that exact line is absent. The script is safe to rerun. If it stops, inspect its replacement snippet and add those fields/validator manually inside your existing `Settings` class.

Confirm Redis supports pending-message recovery:

```bash
docker compose --env-file .env.compose exec rag-service python -c "import os,redis; print(redis.Redis.from_url(os.environ['REDIS_URL']).info('server')['redis_version'])"
```

Use Redis 6.2 or newer. The event consumer's Redis account needs its existing stream permissions plus `XAUTOCLAIM`. Use your Redis administration credentials to inspect the version if INFO is restricted for the application account.

Append the values in `docs/step07_env_additions.env` to `.env.compose`, set a real long random MinIO password, and retain the working database/Redis URLs. These local-development MinIO credentials are used for both server initialization and the application. The bucket is private by default and this step creates no public bucket policy.

The overlay sets `STORAGE_BACKEND` from `RAG_STORAGE_BACKEND`; editing only the service `.env` will not override Compose's setting.

## 2. Use both Compose files from now on

Define this convenience function in your current Git Bash terminal, from the repository root:

```bash
dc() {
  docker compose --env-file .env.compose -f docker-compose.yml -f docker-compose.minio.yml "$@"
}
```

Run:

```bash
dc config --quiet
dc build rag-service minio
dc up -d minio
dc run --rm minio-init
```

The first MinIO build downloads the pinned upstream source and Go modules. The runtime image contains the compiled server, certificate/health-check tools and license; the Go compiler remains in the builder stage. It is based on `RELEASE.2025-10-15T17-29-55Z`, whose upstream release instructs users to build containers from source. This is a local integration image, not a claim of a currently maintained production distribution.

Sources:
- https://github.com/minio/minio/releases/tag/RELEASE.2025-10-15T17-29-55Z
- https://docs.aws.amazon.com/boto3/latest/guide/configuration.html
- https://redis.io/docs/latest/commands/xautoclaim/

Expected initializer output: `MinIO bucket ready ...`. MinIO API is available to containers at `http://minio:9000`, and from your computer at `http://localhost:9000`. A console, where provided by this upstream edition, is on `http://localhost:9001`; CLI checks below do not depend on console features. MinIO data uses the project-scoped named volume `minio-data`.

## 3. Run backend and cleanup checks before enabling the API

Stop only the RAG API while testing cleanup, so its background cleanup loop cannot race the integration script:

```bash
dc stop rag-service
dc run --rm --no-deps rag-service python -m app.tests.integration.check_source_storage
dc run --rm --no-deps rag-service python -m app.tests.integration.check_source_cleanup
```

The first verifies actual write/read/checksum and repeated deletion. The second creates a random disposable owner/document/source, tests deletion rollback, deactivation preservation, a simulated storage outage and cleanup retry, then removes its own test rows and source. It does not create an Auth user or publish a real Redis event. If it is interrupted before its finally block, cleanup of its random test rows may be needed.

The schema remains at the Step 5 revision:

```bash
dc run --rm --no-deps rag-service alembic current
dc run --rm --no-deps rag-service alembic heads
```

Both should remain `a6f31c9e204b`. Do not generate a new migration for this storage change.

## 4. Start and verify through the endpoints

```bash
dc up -d --force-recreate minio-init
dc up -d rag-service
dc ps
dc logs --tail=100 rag-service minio-init
```

Auth defaults to port 8001 and RAG to port 8000, as in Step 6. Log in and verify existing listing/retrieval/search. Upload one new document through RAG and copy its returned document UUID. Verify the actual source and persisted metadata:

```bash
dc exec rag-service python -m app.tests.integration.check_document_source YOUR_DOCUMENT_UUID
```

Expected: `... OK (minio)`. Search the new document's contents. The source URI returned in metadata is an internal locator, not a public download URL.

Restart MinIO and verify the same source remains readable:

```bash
dc restart minio
```

Wait until MinIO is healthy in `dc ps`, then rerun the document-source check and search. Finally, use a disposable Auth test user to verify a real `user.deleted` event removes its documents and emits `source_cleanup_completed` in RAG logs. Do not use an account with data you want to retain for this deletion test.

## Existing files and rollback

Existing documents/embeddings are not migrated or re-embedded. Relative source paths still resolve through the old upload bind mount. Absolute Windows paths cannot be opened by a Linux container; such rows require a reviewed path mapping rather than an automatic rewrite. Cleanup refuses paths outside the configured upload directory, leaving its intent pending for correction.

To switch NEW writes back to local, set `RAG_STORAGE_BACKEND=local` in root `.env.compose`, then run `dc up -d --force-recreate rag-service`. Keep the MinIO overlay and credentials available: already stored MinIO objects still require them for reads/deletes. Do not switch back to the old code while object URIs exist.

`dc down` retains the named MinIO volume. Do not use `down -v` unless you intend to delete its source objects. Commit the updated service `pyproject.toml`/`uv.lock` and new code/config examples on `production-refactor`; keep credentials out of Git. Copy the environment additions to your root example as well, using placeholders.

## Current limits and verification

The upload flow still saves bytes before its initial DB transaction. Caught failures create cleanup intents, but a hard process termination in that gap, or simultaneous failure of storage and the cleanup-intent database write, can leave an untracked source. The worker cutover needs preallocated source identities and orphan reconciliation before this is treated as a fully crash-safe ingestion workflow. There is no automatic retry of failed ingestion yet. No document DELETE endpoint was present in the supplied endpoint file; this step wires user deletion, without inventing an extra endpoint.

Six deterministic storage tests passed in the authoring environment, and the Python syntax, config patch and Compose overlay were checked. Docker, PostgreSQL and Redis services are unavailable there, so the actual builds and integration checks above must run on your machine. After these pass, the next implementation step is the single worker and ingestion queue.
