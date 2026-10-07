# Step 11: shared CPU BGE ONNX embeddings

Step 10B: user reports all endpoints working. Branch production-refactor.
Keep rag-service, one rag-worker, Docling Serve and the GitHub platform-auth dependency.

## Intended setup

Add one embedding-service container using ONNX Runtime CPU. Both rag-service
(query embeddings) and rag-worker (document chunk embeddings) call it over HTTP.
One model session is loaded per embedding-service process, with bounded inference
concurrency. Chunking remains in rag-worker and Docling Serve remains the parser.
PostgreSQL/pgvector retains 768 dimensions. Existing Redis roles and MinIO storage
remain in use. This is an inference service, not a second ingestion worker.

## Exact source inputs needed

The current ingestion factory and search route are available, but the concrete
embedder and retrieval implementations have not been supplied. These determine
query-prefix handling, normalization, truncation and interfaces. Capture them
before producing replacement files; do not infer output behavior from the model
name or vector dimension alone.

Use the read-only collector in this package from repository root:

```bash
python scripts/collect_step11_embedding_inputs.py
```

Upload its output step11_embedding_inputs.zip. No app changes, service restart or
uv dependency installation is needed to collect the handoff. It contains six
explicit Python files, small JSON model configurations, an inventory of weights'
presence/size, and allowlisted non-secret model settings. Full .env files, weights,
documents and DB contents are excluded. Missing files are listed in manifest.json.
If your BGE model lives elsewhere:

```bash
python scripts/collect_step11_embedding_inputs.py --model-dir "YOUR_MODEL_DIRECTORY"
```

The collector refuses to overwrite an existing output. Review the selected source
files before sharing, as source code can contain custom values. If you prefer
manual upload, the required source files are:

- app/rag/ingestion/embeddings/sentence_transformers_embedder.py
- app/rag/retrieval/factory.py
- app/rag/retrieval/vector_retriever.py
- app/rag/retrieval/hybrid_retriever.py
- app/rag/retrieval/base.py
- app/rag/ingestion/model_paths.py

Paths are relative to services/rag-service. Also provide the BGE model's modules.json,
1_Pooling/config.json, sentence_bert_config.json, config_sentence_transformers.json,
config.json and tokenizer_config.json if available. No model weights needed.

## Stepwise implementation

11A: audit current document/query encoding and model configs. The supplied folder
structure lists onnx/model.onnx; confirm it is still present and compatible before
reusing it. Verify graph input/output names, dtypes and dynamic batch/sequence axes.

11B: build services/embedding-service with a CPU-only runtime. Load local tokenizer
and ONNX graph; reproduce the audited maximum length, padding, special tokens,
pooling, normalization and query/document prefix behavior. Start with full-precision
parity, leaving quantization for a separate measured change. One uvicorn process,
one loaded session, bounded batches/queue and inference off the event loop.

11C: compare local existing embeddings against the service on identical queries
and document chunks, including short/long/Unicode text and different batch sizes.
Check vector count/order, 768 dimensions, finite values, norms, numerical similarity
and retrieval rankings on a fixed corpus. Thresholds are chosen for the actual
graph and baseline, not invented before examining them. Batch versus single-text
results must be stable. If the existing runtime already uses ONNX, compare that
actual path as the baseline rather than assuming PyTorch inference.

11D: add a shared HTTP embedding client and two adapters: the ingestion factory
uses document mode; the retrieval factory uses query mode. Apply a query prefix
exactly once, where the audited implementation requires it. Verify response model,
artifact/behavior revision, count, order and dimensions. Bound request size/timeouts;
queue attempts retry service outages, API searches return a clear availability
error. No silent switch to a different model on failure. Preserve keyword-only
retrieval if its current implementation needs no embedding.

11E: drain ingestion jobs before changing processing fingerprints and recreate API
and worker with matching settings, as in Step 10B. Verify remote embeddings for new
uploads and searches over existing documents, plus lifecycle cleanup during an
embedding outage. Reuse existing vectors only if behavior/numerical parity passes.
If representation changes, plan versioned re-embedding explicitly; matching 768
dimensions alone does not establish compatibility. No automatic vector deletion.

11F: Step 12 then removes unused runtime dependencies and splits/slims images.
Audit local parser fallback and optional local reranker before removing PyTorch.
Worker still needs the chunking tokenizer until tokenization/chunking is changed
in a separate stage. Kubernetes remains deferred.

## Proposed new and modified paths

| Path | Action |
| --- | --- |
| services/embedding-service/pyproject.toml | New independently locked runtime dependencies |
| services/embedding-service/uv.lock | Generate after selecting compatible pinned CPU packages |
| services/embedding-service/Dockerfile | New CPU image; no PyTorch in production runtime |
| services/embedding-service/app/main.py | New health/readiness/model-info/embedding endpoints |
| services/embedding-service/app/encoder.py | New tokenizer + ONNX inference + pooling/normalization |
| services/embedding-service/app/schemas.py | New bounded request/response contract |
| services/embedding-service/app/config.py | New validated runtime configuration |
| services/embedding-service/tests/ | Meaningful parity, batch-order and failure checks |
| docker-compose.embedding.yml | New fifth overlay with read-only model mount |
| scripts/dc.sh | Include all five overlays |
| services/rag-service/app/rag/embeddings/client.py | New shared HTTP client |
| services/rag-service/app/rag/ingestion/embeddings/http_embedder.py | New ingestion adapter |
| services/rag-service/app/rag/ingestion/factory.py | Select remote document encoder |
| services/rag-service/app/rag/retrieval/factory.py | Select remote query encoder; preserve reranking |
| services/rag-service/app/rag/retrieval/* | Modify only as required by actual interfaces |
| services/rag-service/app/core/config.py | Add service/revision/timeouts settings |
| services/rag-service/app/workflows/policy.py | Fingerprint verified embedding contract |
| services/rag-service/app/tests/integration/check_embedding_service.py | Add live parity/connectivity check |

Runtime source layout is planned here; the next patch will give actual replacement
files and build/test commands grounded in the missing source inputs. Keep your
current services running during this preparation.

## Proposed HTTP contract

Use a stable internal endpoint POST /v1/embeddings with texts and input_type
(document or query), plus expected model/behavior revision. Return vectors in input
order with model/revision/dimension metadata. Add GET /health, /ready and /v1/model
for diagnostics. A future TEI implementation adapts behind the same RAG client
interfaces. This is a proposed internal contract, not a claim of OpenAI compatibility.

## Model correctness references

BAAI's model card documents CLS pooling and query instructions. Sentence Transformers
notes that direct ONNX use needs pooling/normalization outside the exported transformer.
The actual installed model's modules and your current encode calls remain the migration
baseline. Do not change retrieval semantics simply to follow a different example.

https://huggingface.co/BAAI/bge-base-en-v1.5
https://www.sbert.net/docs/sentence_transformer/usage/efficiency.html

## Deferred SSE requirement

When LLM generation is added: stream token/text deltas over SSE and add document
status events, with owner-scoped auth, cancellation/disconnect handling, done/error
events and polling fallback. Do not add this during the embedding migration.
