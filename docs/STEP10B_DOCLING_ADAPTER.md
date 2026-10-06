# Step 10B: route worker parsing to Docling Serve

Branch: production-refactor. Keep services/rag-service and one rag-worker.
Server supplied by user: docling-serve 1.21.0, docling 2.96.1, core 2.78.0.
The pasted attachment is OpenAPI, not a sample conversion result.

## Plan and resulting behavior

1. Apply adapter/config patch while keeping the current local parser active.
2. Run unit checks, rebuild the existing shared API/worker image, and run the
   direct remote compatibility probe with a real PDF and production tokenizer.
3. Stop the API accepting new jobs; let the existing worker drain old jobs.
4. Stop the worker, set the parser backend in root .env.compose, then recreate
   API and worker together. New uploads use remote conversion.
5. Verify status -> ingested, search, outages/retries and user deletion.

API -> durable PostgreSQL outbox -> Redis -> existing rag-worker. Worker reads
bytes from MinIO, posts them to Docling Serve, reconstructs ParsedDocument.native,
chunks using the same hybrid algorithm/tokenizer, embeds using the current local
embedder, and commits only with a live processing lease. Model/network work stays
outside database transactions. Query embedding is unchanged until Step 11.
Docling Serve runs its local engine with one conversion thread and CPU execution.
It is a conversion service; it does not consume the RAG Redis stream.

## What is supplied

| Path | Change |
| --- | --- |
| docker-compose.docling.yml | Backend selector for API/worker, expected server versions, readiness, CPU/concurrency limits |
| scripts/dc.sh | Four Compose overlays |
| scripts/apply_step10b_config.py | Add settings and validators without replacing your current config |
| app/rag/ingestion/parsers/docling_serve_parser.py | Multipart JSON conversion adapter, preflight, bounded I/O, rich native decoding |
| app/rag/ingestion/parsers/docling_document.py | Core-only projection shared by parsers |
| app/rag/ingestion/parsers/docling_parser.py | Existing local parser uses shared projection; remains available |
| app/rag/ingestion/chunking/docling_chunker.py | Same uploaded wrapper; imports HybridChunker directly from core |
| app/rag/ingestion/factory.py | Select local or remote parser |
| app/workflows/policy.py | Remote versions/adapter revision included in processing fingerprint; local fingerprint unchanged |
| app/workflows/state.py | Persist parser provenance in the same successful lease-guarded commit |
| app/cli/check_ingestion_drained.py | Read-only rollout gate |
| app/tests/integration/check_docling_serve.py | Real server -> native decode -> production hybrid chunking probe |
| app/tests/unit/test_docling_serve_parser.py + fixtures | HTTP/failure/cancellation and cross-version tests |
| docs/RAG_REFACTOR_ROADMAP.md | SSE deferred to LLM generation |

All app paths above are relative to services/rag-service. Uploaded tokenizer and
pyproject are retained as-is. This patch adds no dependency, changes no lockfile,
and needs no migration. Current Docling 2.87.0/core 2.74.0 remain installed. Slim
images come after remote embeddings are working.

## Cross-version compatibility

Both core 2.74 and 2.78 advertise document schema 1.10.0, but 2.78 adds language
and entities metadata which 2.74 rejects as unnamed custom fields. The adapter
handles these known additions: drops null values and preserves populated values
as docling_serve__language / docling_serve__entities custom metadata in the native
document. No table, heading, description or page structure is removed. Other
unrecognized structural changes fail closed. The test fixture was exported by
core 2.78, then decoded/chunked by core 2.74 with Pydantic 2.9.2. A real conversion
probe is still mandatory before enabling this backend.

## 1. Apply and test

Extract the ZIP into repository root on production-refactor. These replacement
files assume your Step 9 versions except for the supplied uploaded chunker.
If you have additional custom changes, merge them before applying. The config
script checks the parser declaration and stops if it differs; it also retains
a backup. Do not overwrite pyproject or uv.lock.

```bash
python scripts/apply_step10b_config.py
source scripts/dc.sh
cd services/rag-service
uv sync --locked
uv run python -m unittest app.tests.unit.test_docling_serve_parser app.tests.unit.test_ingestion_contract -v
cd ../..
dc config --quiet
dc build rag-service
dc up -d --force-recreate docling-serve
dc ps docling-serve
```

Expect 25 tests. Existing API/worker containers keep their previous image until
recreated; the new image is used for probes. Wait for docling-serve to be healthy.
Do not set RAG_PARSER_BACKEND=docling_serve yet.

## 2. Run a real compatibility probe

Place a small non-sensitive PDF at:
services/rag-service/data/uploads/docling_probe.pdf
This existing bind mount makes it visible to the probe container. The probe only
reads the file and talks to Docling Serve. It does not create document DB rows,
Redis jobs, MinIO objects or embedding vectors.

```bash
dc run --rm --no-deps rag-service python -m app.tests.integration.check_docling_serve data/uploads/docling_probe.pdf --approx
```

Then run with your actual locally installed BGE tokenizer:

```bash
dc run --rm --no-deps rag-service python -m app.tests.integration.check_docling_serve data/uploads/docling_probe.pdf
```

Expected final line: Remote conversion -> native decode -> hybrid chunking: OK.
Use a PDF containing a table and inspect labels/page references. Test DOCX/PPTX
and any additional formats you use similarly; pass each file's actual extension.
Remove the temporary probe files after checking. A missing local tokenizer is a
model mount/download issue; the approx check does not prove production tokenization.

For a host uv run, supply --url http://127.0.0.1:5001 and a host-visible file path.
Inside Compose the URL is http://docling-serve:5001, never localhost.

## Picture descriptions

If RAG_PICTURE_DESCRIPTION_ENABLED is false, no additional configuration needed.
If enabled, the adapter forwards your configured prompt/model/backend. It uses
version-pinned legacy fields advertised by this OpenAPI. Before probing, add to
root .env.compose:

DOCLING_SERVE_ALLOW_CUSTOM_PICTURE_DESCRIPTION_CONFIG=true

For an API vision backend also add:
DOCLING_SERVE_ENABLE_REMOTE_SERVICES=true

Then recreate docling-serve and probe a document containing a picture. The
vision model/endpoint must be available from docling-serve; worker-local model
paths do not apply to this container. Default picture threshold 0.05 is supported.
Other thresholds stop configuration validation until a server preset is added;
they are never silently replaced. Server-side picture inference/downloads need
verification on your machine. Do not turn this feature off just to bypass a failed
compatibility check if you rely on it.

## 3. Drain old jobs before switching

Changing backend changes the processing fingerprint. Prevent old jobs being
claimed by a worker with the new fingerprint:

```bash
dc stop rag-service
dc run --rm --no-deps rag-service python -m app.cli.check_ingestion_drained
```

Keep your existing rag-worker running. If the gate lists pending/processing
rows, wait for it to finish/retry them and rerun the gate. Do not remove them or
flush Redis. If jobs remain stuck, inspect logs and resolve that before switching.
When the gate says OK, stop the worker:

```bash
dc stop rag-worker
```

Now add/update this single line in root .env.compose:

```dotenv
RAG_PARSER_BACKEND=docling_serve
```

The fourth overlay applies that value to both API and worker. No need to change
service .env for Compose. Then run:

```bash
dc config --quiet
dc up -d --force-recreate minio-init
dc up -d --force-recreate rag-service rag-worker
dc logs --tail=100 rag-worker
dc logs --tail=100 docling-serve
```

Recreating minio-init ensures the init container is pinned to the newly built
shared image when dependencies require its successful completion. Bucket creation
is idempotent and does not remove existing objects. All four overlays are required.

## 4. Verify end to end

1. Upload PDF. POST stays 202/pending.
2. Poll GET /api/v1/documents/{id}; expect processing -> ingested.
3. Successful metadata includes parser_provider=docling_serve, parser_version=1.21.0,
   parser_docling_version=2.96.1 and parser_core_version=2.78.0 plus usual statistics.
4. Check the matching request appears in docling-serve logs; verify search answers
   still retrieve table/text chunks. Repeat the formats your application supports.
5. Stop docling-serve, upload a test file, observe bounded retries and retained
   source, then restart it. Restart before the 3-attempt budget is exhausted if
   you want that job to recover. A terminal failed job needs a new upload; do not
   claim that restarting automatically requeues terminal failures.
6. With a disposable user, verify deletion while a document is queued/processing
   still removes DB rows and MinIO source and cannot be undone by late conversion.

```bash
dc stop docling-serve
# Upload the disposable test document and observe status/retry_count.
dc up -d docling-serve
```

Worker starts independently of Docling readiness so lifecycle cleanup keeps running
through inference outages. Transport/408/429/5xx errors retry. Version/API mismatch
and malformed/failed conversion also retry only up to the existing attempt budget.
Partial success is rejected instead of indexing incomplete content. Server error
bodies and API secrets are not logged by the adapter.

## Troubleshooting and rollback

DoclingServeVersionMismatch: compare /version with the expected deployed pin.
DoclingServeSchemaMismatch: run the direct probe and inspect compatibility, response
limit and required multipart fields. Do not blindly upgrade the entire environment.
DoclingServeConfigurationError: inspect authentication/server options (including
picture config flags); 422 is request validation, not proof the PDF is bad.
DoclingServeUnavailable: check docling readiness, network and resource usage.

To roll back, stop API uploads, drain remote jobs using the same read-only gate
while the remote worker is still running, then stop worker, set
RAG_PARSER_BACKEND=docling in root .env.compose and recreate API/worker together.
Do not change fingerprints while jobs are active. No migration rollback required.
Previously ingested content remains searchable.

## Validation and next step

25 unit tests passed locally using real core 2.74.0, HTTPX 0.27.2 and Pydantic 2.9.2;
HTTP requests use MockTransport. Fixtures cover a core 2.78 export including table,
heading, image description and page provenance. Missing project exception/model-path
modules were stubbed only in the isolated test harness; the core codec/chunker were
real. Configuration patch, local fingerprint preservation, AST and YAML/shell syntax
are checked. Real Docker/DB/Redis/MinIO/PDF conversion must run on your machine.

After successful rollout: Step 11 shared CPU BGE ONNX embeddings, then slimmer
images. SSE token streaming and document status events are recorded for the LLM
stage; neither is added here.
