# Step 12: separate slim API and worker images

Use branch `production-refactor`. Step 11 uploads/endpoints are working. The API and
worker currently still share the old image containing local ingestion/model libraries.
This step changes their installed dependencies and mounts, while retaining one worker.
No database migration, model change, vector rewrite or re-ingestion is required.

## Implementation plan

1. Move ingestion/model dependencies out of the base RAG dependency list.
2. Create separate API and worker build targets and distinct image tags.
3. Copy the existing BGE tokenizer into a separate, hash-verified directory.
4. Configure the API to have no model mount, and the worker to mount only tokenizers.
5. Add startup guards and image/import checks so accidental local-model configuration
   fails before accepting work.
6. Build while current containers continue running, drain ingestion, then recreate
   only the API and worker. Verify uploads, retrieval and user deletion.

| Container | Responsibilities and installed model libraries |
| --- | --- |
| rag-service | Authentication, upload/source storage, job creation, document status, retrieval and HTTP embeddings; no Docling/Transformers/PyTorch/ONNX runtime |
| rag-worker (one) | Redis/outbox ingestion, lifecycle cleanup, remote parsing, structured chunking and HTTP embeddings; Docling Core 2.74.0, Transformers 4.57.6 and tokenizer 0.22.2; no PyTorch/Docling converter/ONNX runtime |
| docling-serve | Existing remote document conversion service; unchanged |
| embedding-service | Existing CPU ONNX model inference service; unchanged |

The worker still needs Docling Core to reconstruct DoclingDocument and run
HybridChunker, and a real BGE tokenizer to enforce the same token limits. Neither
requires installing PyTorch. Transformers may log that model frameworks are absent;
that message is expected here. Existing original model files stay where they are for
the embedding service. Only five small tokenizer/config files are copied for the worker.
The total image sizes must be measured after building; no fixed size is promised.

## Files in this overlay

| Path | Action |
| --- | --- |
| services/rag-service/Dockerfile.runtime | New two-target Dockerfile; existing Dockerfile retained |
| docker-compose.runtime.yml | New sixth overlay; replaces API/worker model mounts |
| scripts/dc-step12.sh | New dc12 helper; existing dc helper retained |
| scripts/apply_step12.py | Guarded edits to pyproject.toml/config.py, with backups |
| scripts/prepare_step12_tokenizer.py | Copy tokenizer files only after checking Step 11 hashes |
| scripts/check_step12_compose.py | Check resolved Compose settings without printing secrets |
| scripts/test_step12_setup.py | Five offline setup/guard tests using the standard library |
| app/core/runtime_roles.py | Enforce compatible slim-container configuration |
| app/cli/check_runtime_image.py | Installed-dependency and live import/tokenizer checks |

App paths above are within services/rag-service. Shared package names/imports and the
external GitHub platform-auth dependency remain as configured. The overlay does not
include a replacement uv.lock: regenerate your actual lock against your repository's
shared packages and GitHub dependency in step 2 below.

## 1. Extract and check prerequisites (repository root, Git Bash)

Extract the ZIP into your monorepo root, adding its files. Then:

```bash
git branch --show-current
docker compose version
source scripts/dc.sh
source scripts/dc-step12.sh
```

Expect production-refactor. Docker Compose must be 2.24.4 or newer, because the new
overlay uses !override to replace volume lists. Upgrade Docker Desktop if necessary.
Keep both helpers: dc uses the working Step 11 configuration; dc12 adds Step 12.
Source them again in every new terminal. Do not redefine dc until verification passes.

If your API/worker have extra custom volume mounts, add them to the new overlay before
using it: !override replaces the entire list. The supplied overlay preserves legacy
local upload mounts and replaces the worker's full model mount with the tokenizer copy.

## 2. Apply dependency/settings changes and regenerate the lock

```bash
cp services/rag-service/uv.lock services/rag-service/uv.lock.step12.bak
python scripts/apply_step12.py
python scripts/prepare_step12_tokenizer.py
python scripts/test_step12_setup.py
cd services/rag-service
uv lock
uv lock --check
cd ../..
```

Run the lock backup command only on the first application; retain the original backup
on retries. apply_step12.py backs up pyproject.toml and config.py as *.step12.bak. It
checks both edits before writing either and is safe to rerun. It stops if dependencies
or expected declarations differ; send the stated file in that case, rather than forcing
the edit. Existing unrelated settings and the GitHub auth source are preserved.

The dependency layout becomes:

- Base dependencies: API runtime plus database, Redis/auth, HTTP and storage clients.
- worker extra: Docling Core chunking, Transformers, tokenizer and Hugging Face Hub.
- local-models extra: original local Docling/SentenceTransformer dependencies plus
  worker dependencies, for explicit local development and parity probes.
- dev group: testing/linting tools and existing other development dependencies.

uv resolves every extra into one lockfile, so torch/docling can still appear in uv.lock.
The API installation selects no extras; the worker selects only worker. The presence
of an optional package in the lockfile does not mean it is installed in either image.
Both builds use --locked --no-dev and enforce the installed dependency boundary.
Do not use --all-extras for these production images.

Tokenizer preparation checks config.json, tokenizer_config.json, special_tokens_map.json,
tokenizer.json and vocab.txt against services/embedding-service/model-manifest.json.
It creates services/rag-service/data/tokenizers/BAAI--bge-base-en-v1.5. It never copies
weights. If you used another original model folder in Step 11, pass --model-dir to the
preparation script. Keep the default destination used by this Compose overlay.

## 3. Check settings and build while current containers keep running

Keep these values in your existing .env.compose:

```dotenv
RAG_PARSER_BACKEND=docling_serve
RAG_EMBEDDING_BACKEND=http
```

Reranking can remain disabled. If it is enabled, the slim images require its existing
API backend; a local cross-encoder requires the local-models development environment.
RAG_RUNTIME_ROLE and RUN_LIFECYCLE_CONSUMER are set by the overlay: api/false and
worker/true. URLs, credentials and the Step 11 embedding revision come from the earlier
overlays and contract.env. Do not change that revision for this packaging step.

```bash
dc12 config --quiet
dc12 config --format json | python scripts/check_step12_compose.py
docker tag rag-platform/rag-service:local rag-platform/rag-service:step11
dc12 build rag-service rag-worker
```

Keep the step11 image tag until this step is verified. Tag it only before the FIRST
Step 12 build; do not overwrite that rollback tag with a new slim image on retries.
The build checks required shared packages and rejects heavy inference dependencies.
It also imports the real Docling Core chunker/tokenizer in the worker environment.
Existing running containers keep their current image until recreated.

## 4. Drain and roll out the two new images

Stop new uploads by stopping the API. Leave the current worker running until jobs finish:

```bash
dc stop rag-service
dc exec rag-worker python -m app.cli.check_ingestion_drained
```

If the drain check reports pending/processing documents, keep the old worker running,
wait for those jobs to reach ingested or failed, and run the check again. Investigate
any stuck job before proceeding. Then:

```bash
dc stop rag-worker
dc12 up -d --no-deps --force-recreate rag-worker rag-service
dc12 ps
dc12 logs --tail=100 rag-service rag-worker
dc12 exec rag-service python -m app.cli.check_runtime_image --role api
dc12 exec rag-worker python -m app.cli.check_runtime_image --role worker
dc12 exec rag-service python -m app.tests.integration.check_container_connections
```

Auth, MinIO, Docling Serve and embedding-service must already be running from Step 11.
Only API/worker are recreated here. No volumes are removed and Redis streams/consumer
groups are retained. If a startup guard reports a local backend, fix that environment
value; do not install model dependencies into the slim container.

Expected: API healthy, worker running; API dependency/import check OK; worker dependency,
remote parser/chunker and local tokenizer checks OK; existing DB/Redis connection
checks OK. The image check performs imports/local tokenization, with no DB/Redis writes.

## 5. End-to-end acceptance

1. Upload a PDF using Postman: POST /api/v1/documents returns 202 and pending.
2. Poll GET /api/v1/documents/{id} until ingested; verify processed_at and retained
   embedding/parser provenance. Existing Location header/polling behavior stays the same.
3. List/retrieve documents and search with a known query; check the expected results.
4. Verify the original source exists in MinIO. Delete a test user and verify its DB
   records and objects are eventually removed by the single worker.
5. Check logs for unexpected ModuleNotFoundError or attempts to load local embedding
   weights. Record the image sizes/resource usage:

```bash
docker image ls rag-platform/rag-service
docker image ls rag-platform/rag-worker
docker stats --no-stream
```

The image sizes exclude bind-mounted weights. Total system resource use still includes
Docling Serve and embedding-service. A smaller API image does not remove those services'
inference cost. No need to rerun numerical parity solely for packaging when the original
Step 11 model contract and files are unchanged; if you have not yet passed the Step 11
parity gate, run it using the local-models environment before marking migration complete.

## Local development after the split

From services/rag-service, use uv sync --locked --extra worker for worker development
and uv run --locked --extra worker ... for worker commands. For old local model code or
Step 11 parity, select --extra local-models for BOTH uv sync and uv run. Keep runtime
role development locally (the default) and choose backends appropriate to that environment.
Plain uv sync installs base + dev; it does not select worker/local-models dependencies.

Once acceptance passes, use dc12 for subsequent operations, or deliberately update
your dc helper to include docker-compose.runtime.yml last.

## Rollback to the working Step 11 image

If Step 12 fails, do not rebuild the old Dockerfile against the new dependency layout.
Restore the saved Step 11 image and original metadata/config instead:

```bash
dc12 stop rag-service
```

If the new worker is running with active jobs, let it drain using the same drain check
before stopping it. If it cannot start, stop it; the existing retry/lease recovery will
resume jobs when the Step 11 worker returns. Then:

```bash
dc12 stop rag-worker
cp services/rag-service/pyproject.toml.step12.bak services/rag-service/pyproject.toml
cp services/rag-service/app/core/config.py.step12.bak services/rag-service/app/core/config.py
cp services/rag-service/uv.lock.step12.bak services/rag-service/uv.lock
docker tag rag-platform/rag-service:step11 rag-platform/rag-service:local
source scripts/dc.sh
dc up -d --no-deps --force-recreate rag-worker rag-service
dc ps
```

Use dc, which excludes the sixth overlay and again mounts the original model directory.
The original Dockerfile and Step 11 code are retained; new Step 12 files can remain
unused. Keep all volumes, the original model directory and contract files.

## Validation limits and later work

Prepared here: dependency separation, guarded patching, tokenizer hash/allowlist checks,
role checks and actual Docling Core/Transformers tokenization/chunking without PyTorch.
Docker is unavailable in the preparation environment and your full current repository
is not mounted here. Generate the lock and perform the image/endpoint checks locally.
Do not treat the supplied overlay as evidence that your container builds have passed.

SSE remains on the roadmap for LLM generation: live token/text streaming plus document
status events. It is not part of Step 12. Proceed to the next feature only after the
new API/worker image checks and end-to-end acceptance above pass.

References: [uv optional dependencies](https://docs.astral.sh/uv/concepts/dependencies/),
[uv sync extras](https://docs.astral.sh/uv/concepts/projects/sync/), and
[Docker Compose !override](https://docs.docker.com/reference/compose-file/merge/).
