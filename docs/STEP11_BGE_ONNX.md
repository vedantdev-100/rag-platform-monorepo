# Step 11: shared CPU BGE ONNX embeddings

Branch production-refactor. Keep services/rag-service, one rag-worker, external
platform-auth dependency and existing Docling Serve. No database migration.

## Audit and implementation plan

Your submitted implementation uses SentenceTransformer.encode(normalize_embeddings=True)
for both documents and queries, with no instruction prefix. The model modules are
Transformer -> CLS Pooling -> Normalize, and max_seq_length=512/do_lower_case=true.
The extra encode normalization is preserved. Existing ONNX file is present (435,811,539
bytes). This step keeps those semantics; it does not add a BGE query prefix or quantize.

1. Create an immutable model/behavior contract from existing files.
2. Build the independent ONNX CPU service and test it while current API/worker keep
   their existing backends.
3. Run real numerical and retrieval parity against your current PyTorch encoder.
4. Drain old jobs and switch API and worker to HTTP embeddings together.
5. Verify uploads, retrieval, lifecycle deletion and outage handling.
6. Step 12 later removes unused dependencies and creates slim API/worker images.

The API sends query texts; the worker sends chunk texts. The embedding service owns
one CPU ONNX session, batches up to 8 texts per inference call, accepts up to 32 texts
per HTTP request, and runs one inference request at a time with a bounded queue.
No PyTorch/Transformers is required in its production image. It is an inference
service, not another RAG ingestion worker. Worker lifecycle/cleanup stays independent
of inference availability. The API/worker still use their current shared image until
Step 12. The worker still needs a local BGE tokenizer for hybrid chunking.

## New/modified paths

| Path | Result |
| --- | --- |
| services/embedding-service/ | New independent CPU runtime, uv.lock, Dockerfile and tests |
| docker-compose.embedding.yml | Fifth overlay, local port 5002, read-only model/manifest mounts |
| scripts/dc.sh | Includes all five overlays and generated contract.env |
| scripts/prepare_step11_model.py | Hash existing ONNX/tokenizer/config files; no download/export |
| scripts/apply_step11_config.py | Preserve config/search code; add settings and search 503 handling |
| app/rag/embeddings/client.py | Shared HTTP embedding implementation, response identity/shape/norm checks |
| app/rag/ingestion/factory.py | Add HTTP encoder; preserve remote Docling and local fallbacks |
| app/rag/retrieval/factory.py | Request query mode; keep existing retrievers/reranking |
| app/rag/retrieval/hybrid_retriever.py | Embed before SQL; sequential reads on one AsyncSession; same RRF |
| app/workflows/policy.py | Include embedding contract revision in new job fingerprint |
| app/workflows/state.py | Record embedding revision in the existing guarded success transaction |
| app/tests/integration/check_embedding_service.py | Live numerical, batching and ranking parity gate |
| app/tests/unit/test_http_embeddings.py | Client and hybrid transaction ordering checks |

App paths are relative to services/rag-service. No rag-contracts/rag-persistence
changes, no existing RAG dependency/lockfile changes, no rewriting stored vectors.
Generated model-manifest.json pins all relevant file hashes; contract.env contains
only the matching revision. Its identity must change when model/behavior changes.
Runtime also checks actual hashes before loading/warming the session.

## 1. Extract and prepare (repository root)

Extract this ZIP on production-refactor. If you made custom changes to the supplied
factory/hybrid files, merge those first. Config/search patch stops when declarations
or the awaited retrieval call differ; send the changed file if that happens.

```bash
python scripts/apply_step11_config.py
python scripts/prepare_step11_model.py
source scripts/dc.sh
dc config --quiet
```

Preparation hashes the roughly 436 MB ONNX file; allow a short wait. Default model
folder matches your supplied structure. If files differ from the uploaded baseline,
resolve that before switching. The generated revision is automatically supplied to
API/worker by the updated dc helper's second --env-file argument. Keep credentials in
your existing .env.compose, not contract.env. Every new terminal must source dc.sh.

If using a different model directory, supply --model-dir and also change the read-only
Compose mount source to the same actual folder. Do not move/download weights just to
apply this step. A changed existing manifest is not overwritten automatically.

## 2. Run tests and build

Service tests use a small generated ONNX graph and real ONNX Runtime, not BGE weights.
They check graph/CLS mechanics, normalization, batch shape, artifact tampering, queue
cancellation, API contracts, limits and error handling.

```bash
cd services/embedding-service
uv sync --locked
uv run python -m unittest discover -s tests -v
cd ../rag-service
uv sync --locked
uv run python -m unittest app.tests.unit.test_http_embeddings app.tests.unit.test_ingestion_contract -v
cd ../..
dc build embedding-service rag-service
dc up -d embedding-service
dc ps embedding-service
dc logs --tail=100 embedding-service
```

Expect 10 service tests and 14 RAG client/queue tests. Wait for healthy status.
Existing API/worker containers continue using their old installed image until
recreated. The new API image is used by the parity probe. Production service Docker
build uses --no-dev; ONNX test graph generation is not installed in its runtime.

Host checks (Postman):
GET http://127.0.0.1:5002/health
GET http://127.0.0.1:5002/ready
GET http://127.0.0.1:5002/v1/model

Model info must show CPUExecutionProvider, dimension 768, CLS, max_length 512 and
empty query/document prefixes. If configured, send X-Api-Key from root .env.compose.

## 3. Mandatory live parity gate

```bash
dc run --rm --no-deps rag-service python -m app.tests.integration.check_embedding_service
```

This loads your existing local SentenceTransformer on CPU, then compares its outputs
against the HTTP service for passages, queries, Unicode, whitespace, empty text and
long-text truncation. It verifies vector norms, batch versus single input, query versus
document mode and top-3 retrieval ranks on a fixed small corpus. It writes no document,
DB row, Redis job or MinIO object. The baseline PyTorch model lives only in the probe
container; it exits afterward. CPU/RAM may temporarily rise during the comparison.

Required final line: Embedding service parity: PASSED.

Numerical gate: minimum cosine >=0.99999, maximum coordinate difference <=0.0001,
unit norm deviation <=0.00001; batch/single <=0.0001 and same fixed-corpus top-3 ranks.
These are strict FP32 migration checks, not a guarantee over every possible document.
Also verify representative searches over your actual existing documents after rollout.
Do not lower thresholds to force a pass or enable the backend if the check fails;
send the output for diagnosis. No automatic re-embedding or vector deletion occurs.

## 4. Drain and switch

Do not change processing fingerprints while jobs are active. Stop new API uploads,
keep the existing worker running until old jobs finish, and use the Step 10B gate:

```bash
dc stop rag-service
dc run --rm --no-deps rag-service python -m app.cli.check_ingestion_drained
```

If pending/processing rows are listed, wait for the old worker and rerun. Once OK:

```bash
dc stop rag-worker
```

Add/update one line in ROOT .env.compose:

```dotenv
RAG_EMBEDDING_BACKEND=http
```

Keep RAG_PARSER_BACKEND=docling_serve. The service .env's older embedding backend is
correctly overridden by this fifth overlay for both containers. Then:

```bash
dc config --quiet
dc up -d --force-recreate minio-init
dc up -d --force-recreate rag-service rag-worker
dc logs --tail=100 rag-worker
```

minio-init uses the shared rebuilt RAG image and retains the existing bucket. The
embedding service is independent: outage must not block worker startup/lifecycle.

## 5. Functional checks

- Upload, poll until ingested, then search. Check previous documents too. New successful
  document metadata must show embedding_backend=http and the generated embedding_revision.
  The DB embedding_model_revision field records the same contract identity.
- Test vector and hybrid retrieval. Hybrid embedding now precedes SQL and reads run
  sequentially; fusion scoring remains unchanged. Keyword-only retrieval uses no
  embedding service.
- Query inference now occurs in embedding-service; API no longer loads BGE for query
  embeddings. Optional local reranker remains local if explicitly enabled.
- Ingestion model work stays outside DB transactions; live lease checks prevent late
  results from restoring a deleted user/document.
- Stop embedding-service and test a search: expect HTTP 503 embedding_service_unavailable
  rather than a different fallback model. Restart it afterward.
- A test upload during an outage follows the existing bounded ingestion retry policy
  and retains its source. Restart before retries exhaust if you expect that job to
  recover. Terminal failed jobs need a new upload; restart alone does not requeue them.
- Verify disposable-user deletion still removes DB rows and MinIO sources, including
  deletion during queued/processing ingestion.

```bash
dc stop embedding-service
# Run a disposable outage check.
dc up -d embedding-service
```

Optional local deployment authentication: root .env.compose can set
EMBEDDING_SERVICE_API_KEY. The fifth overlay supplies it to service and both clients.
No public service port is required in production; local port 5002 is for checks.

## Rollback

Stop new API uploads; while HTTP worker remains running, drain with the same gate.
Stop worker, set RAG_EMBEDDING_BACKEND=sentence_transformers in .env.compose and recreate
API/worker together. Keep the generated contract files for reproducibility. Previously
ingested vectors remain. Original local encoder and dependencies are retained until
Step 12. No migration rollback required.

## Validation performed here

24 tests passed: 10 service tests (real tiny ONNX graph) and 14 RAG client/contract/order
checks. CPU-only service dependencies resolved into uv.lock. Existing non-HTTP processing
fingerprint preserved; script repeatability and Python/shell/YAML checks performed.
Project exception/model-path modules absent from this workspace were stubbed only for
RAG unit tests. Real BGE weights and Docker/DB/Redis/MinIO were not available here: the
live parity gate and end-to-end checks must run on your machine.

## Next milestones

After parity and all functional checks pass: Step 12 slim API/worker images. Keep the
worker's local tokenizer unless a separate chunking change is planned. Audit optional
local reranker/local parser rollback needs before removing PyTorch/Docling dependencies.
SSE token streaming plus document status events remain deferred to LLM generation.

Official runtime references:
https://onnxruntime.ai/docs/api/python/api_summary.html
https://onnxruntime.ai/docs/performance/tune-performance/threading.html
