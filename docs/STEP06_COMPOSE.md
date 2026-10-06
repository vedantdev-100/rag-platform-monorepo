# Step 6 — containerize the currently working Auth and RAG services

Apply this on `production-refactor`, after the UUID normalization fix and Step 5 migration. This overlay adds Compose and a container connectivity check; it replaces only the RAG Dockerfile. It does not replace `pipeline.py`, `app/main.py`, models, migrations or dependencies.

The goal is to prove that your working services run in Docker with the two shared packages before changing storage or ingestion behavior. PostgreSQL and Redis continue running where they are now. This avoids introducing an empty database or a second event stream during the refactor.

## Exact files

| Path, relative to repository root | Action |
| --- | --- |
| `docker-compose.yml` | New; runs Auth and RAG together |
| `.env.compose.example` | New; example container connection settings |
| `.dockerignore` | New, or merge its patterns into an existing root file |
| `services/rag-service/Dockerfile` | Replace the uploaded RAG Dockerfile |
| `services/auth-service/.dockerignore` | Merge with the existing file; keep extra exclusions |
| `services/rag-service/app/tests/integration/check_container_connections.py` | New; read-only dependency checks |
| `docs/STEP06_COMPOSE.md` | New; these instructions |
| `docs/step06_gitignore_additions.txt` | New; append its entries to root `.gitignore` |

Keep your uploaded Auth Dockerfile. Compose overrides its startup command to run the already installed Uvicorn directly. Auth continues installing `platform-auth` from its existing GitHub dependency declaration. The root `packages/platform-auth` directory is excluded from the RAG build.

RAG uses build context `.` with Dockerfile `services/rag-service/Dockerfile`. In the image, the service lives at `/workspace/services/rag-service` and the shared sources at `/workspace/packages/rag-contracts` and `/workspace/packages/rag-persistence`. Thus the existing `../../packages/...` dependency paths remain valid. `uv sync --locked --no-dev --no-editable` installs the shared packages into the image environment. Local development may continue using editable installs.

## 1. Apply and configure

Extract the ZIP into the monorepo root. It contains files relative to that root, not another enclosing project directory. Merge the two ignore files if they already exist. Append the Git ignore additions rather than replacing your existing `.gitignore`.

From the repository root, in Git Bash:

```bash
git branch --show-current
cp .env.compose.example .env.compose
docker compose version
```

Expected branch: `production-refactor`. Use Docker Desktop with Linux containers and Compose V2.

Edit `.env.compose` before continuing:

- Copy each service's CURRENT WORKING `DATABASE_URL`, keeping its user, password, database and required URL parameters. Replace `localhost` with `host.docker.internal` when connecting to the same host-published PostgreSQL instance. The example assumes port 5431 and database `ai_platform`; use your real values. Percent-encode URL password characters as your current working URL does. Compose accepts single-quoted values if literal `$` characters need protection from interpolation.
- Set `AUTH_REDIS_URL` to the existing platform-auth blacklist/rate-limit Redis endpoint, and `EVENTS_REDIS_URL` to the existing lifecycle stream endpoint. Change host to `host.docker.internal` for host-published services. Keep existing Redis DB numbers, credentials, stream and group values. These two URLs can be identical if that is your current setup.
- Retain your current `services/auth-service/.env` and `services/rag-service/.env`; Compose reads them and overrides only the listed settings. The root example is not a replacement for these service files.
- Confirm `services/auth-service/secrets/private_key.pem` and `public_key.pem` exist. The current signing keys are mounted read-only, preserving token verification.
- Confirm `services/rag-service/models` contains the existing BGE/Docling downloads and `services/rag-service/data/uploads` contains existing uploads. These directories are mounted from your current checkout, not copied into the image. Missing bind directories produce an error rather than silently creating empty model directories.

Container-to-container JWKS URL becomes `http://auth-service:8000/.well-known/jwks.json`. Host access defaults to Auth `http://localhost:8001` and RAG `http://localhost:8000`. All other JWT settings remain from your existing service environment files; if your issuer is a URL, preserve its existing value rather than changing it to the Compose hostname.

`host.docker.internal` is supported by Docker Desktop. If your current PostgreSQL/Redis runs remotely, use its actual reachable address instead. If it is another Docker container, keep its existing published host port for this step. On native Linux Docker, host connectivity may need a different setup; this file targets your Windows Docker Desktop environment.

Reference: https://docs.docker.com/desktop/features/networking/networking-how-tos/

## 2. Confirm the local lockfile and build

```bash
cd services/rag-service
uv sync --locked
cd ../..
docker compose --env-file .env.compose config --quiet
docker compose --env-file .env.compose build auth-service rag-service
```

The shared dependencies added in Steps 2–3 must already be in the service's `pyproject.toml` and `uv.lock`. If `--locked` reports stale metadata, update the lock from `services/rag-service` with `uv lock`, review its changes, and rebuild. Do not remove `--locked` from the Dockerfile.

The build performs a shared-package import check. This first RAG image still includes your current Docling and SentenceTransformers dependencies. The model files are mounted separately, but the image is not yet the final lightweight API image. The split happens after external parser/embedding adapters work.

Reference: https://docs.astral.sh/uv/guides/integration/docker/

## 3. Verify DB, shared packages and Redis before starting the API

Keep your existing PostgreSQL and Redis running.

```bash
docker compose --env-file .env.compose run --rm --no-deps rag-service python -m app.tests.integration.check_container_connections
docker compose --env-file .env.compose run --rm --no-deps rag-service alembic current
docker compose --env-file .env.compose run --rm --no-deps rag-service alembic heads
```

Expected: shared model identity OK, four RAG tables present, `vector(768)` retained, both Redis PING checks OK. `current` and `heads` should both show `a6f31c9e204b` after Step 5. This step does not run migrations automatically. If they differ, reconcile the Step 5 migration before starting the API.

The check does not start `app.main`, read stream messages, insert documents, or change rows. PING proves connectivity, not all application Redis permissions; verify login and lifecycle behavior below.

## 4. Start and exercise the actual services

Stop the host-run Auth and RAG Uvicorn processes first. In particular, stop the old RAG process so its lifecycle consumer is not running alongside the container consumer. Keep PostgreSQL and Redis running.

```bash
docker compose --env-file .env.compose up -d auth-service
docker compose --env-file .env.compose ps
```

Wait until Auth is healthy (the check verifies it serves a non-empty JWKS). Then:

```bash
docker compose --env-file .env.compose run --rm --no-deps rag-service python -m app.tests.integration.check_container_connections --http
docker compose --env-file .env.compose up -d rag-service
docker compose --env-file .env.compose ps
```

If Auth is not healthy, use `docker compose --env-file .env.compose logs --tail=100 auth-service` before proceeding. Health checks here indicate HTTP availability; DB/Redis are checked separately by the script and endpoints.

Open Auth docs at `http://localhost:8001/docs` and RAG docs at `http://localhost:8000/docs` if your existing development settings enable docs. Log in through Auth with an existing account, then authorize the RAG docs with its token. Verify:

1. List and retrieve an existing document; search its existing chunks.
2. Upload one new document and search it after ingestion completes.
3. Log out and confirm the revoked token is rejected by RAG.
4. With a disposable test user, upload a document, delete that user through Auth, and confirm the lifecycle consumer removes that user's RAG data. Use only test data for this deletion check.

```bash
docker compose --env-file .env.compose logs --tail=100 rag-service
```

Existing relative source paths such as `data/uploads/...` resolve against the same mounted upload directory. Rows containing absolute Windows source paths are not rewritten by this step; Linux containers cannot open `D:\\...` paths. Existing retrieval uses stored chunks, but source-file operations on those rows require an explicit path migration later. Test the newly uploaded document to verify the container storage path.

## 5. Finish or return to host development

Step 6 is complete when both containers are healthy, connection checks pass, migrations match, and upload/retrieval/authentication work from the containers.

To stop these application containers:

```bash
docker compose --env-file .env.compose down
```

Uploads remain in your existing bind directory. PostgreSQL and Redis are external to this Compose project. You can resume host-run services afterward.

Do not commit `.env.compose`, service `.env` files or signing keys. Commit the Compose file, example, RAG Dockerfile, ignore patterns, check script and instructions on `production-refactor` after verification.

## Following steps

Step 7 adds MinIO plus a storage adapter while retaining support for existing local documents. Next, build one `rag-worker` service containing ingestion, lifecycle and outbox loops. Finally connect Docling Serve and the BGE ONNX embedding service, then remove heavy inference dependencies from the API. There is no placeholder worker here: the existing API still performs ingestion and runs its lifecycle consumer until the worker handoff is implemented.

## Validation supplied with this overlay

Compose YAML and Python syntax were checked, as were build-context paths and package layouts against the uploaded Dockerfiles and earlier overlays. Docker is unavailable in the authoring environment, so image builds, DB/Redis connectivity, and endpoint behavior must be verified using the commands above. The full current auth source and current lockfiles were not uploaded; the Auth Dockerfile is intentionally retained and the actual lockfiles remain authoritative.
