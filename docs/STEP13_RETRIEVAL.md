# Step 13: retrieval finalization before LLM generation

Branch: production-refactor. Keep services/rag-service and the single rag-worker.
This patch was reviewed against your uploaded zip.zip, not an unseen GitHub checkout.
Read the plan before applying. No new service, dependency, lockfile change or database
migration is required. Parsing, chunking and the BGE ONNX embedding contract remain.

## Review findings

Already implemented correctly: HTTP query embeddings, owner-scoped vector/full-text
SQL, GIN/HNSW index declarations, reciprocal rank fusion, chunk/document IDs and
page/heading metadata, optional reranking, and sequential SQL on the shared session.
Query embedding precedes the first SQL read. The existing search response shape is kept.

Confirmed gaps and the changes supplied:

| Finding in uploaded code | Change |
| --- | --- |
| Vector/keyword SQL checked owner only | Both now also require document.status = ingested |
| Explicit top_k limited each hybrid search to that same small count without a reranker | Hybrid uses max(top_k, RAG_RETRIEVAL_CANDIDATES) per branch, fuses that pool, then returns final top_k |
| Missing top_k could return 20 results despite RAG_DEFAULT_TOP_K=5 | Omitted/null top_k consistently returns at most RAG_DEFAULT_TOP_K |
| Query length and top_k were bounded, but blank spaces were accepted | Trim outer whitespace and reject whitespace-only queries; keep 2000-character/50-result caps |
| Environment settings allowed invalid/unbounded retrieval counts | Validate configured limits at startup |
| Remote reranking happened while the SQL read transaction stayed open | Copy retrieved data, roll back the dedicated read transaction, then rerank |
| Provider JSON/index/score assumptions could raise uncontrolled errors | Validate responses and convert request/JSON/index/score failures into sanitized RetrievalError; endpoint returns 503 |
| Search orchestration lived only in its endpoint | Add RetrievalService, reusable by generation through the same factory |

This does not prove live retrieval relevance or speed. SQL isolation, actual query
results and latency must pass the checks below on your running setup. The patch uses
the existing ingested status, not a new completed status.

## Implementation plan

1. Apply guarded edits to the exact reviewed files; stop on unexpected local changes.
2. Keep the same vector/keyword algorithms and HTTP embedding contract.
3. Separate candidate retrieval from final output limits, and normalize request input.
4. Release SQL resources before optional remote reranking.
5. Test validation, owner/status predicates, ranking identity and transaction ownership.
6. Verify live SQL isolation and known-document retrieval through both CLI and Postman.
7. Proceed to LLM generation only after these gates pass.

## Files changed/added

| Path | Result |
| --- | --- |
| packages/rag-persistence/rag_persistence/repositories/chunk_repository.py | Owner + ingested filters; deterministic keyword ties; vector ORDER BY shape retained |
| services/rag-service/app/core/config.py | Bounds on existing result/candidate/RRF/rerank settings |
| app/schemas/search.py | Whitespace validation and strict integer top_k |
| app/api/v1/endpoints/search.py | Use shared retrieval service and controlled upstream errors |
| app/rag/retrieval/factory.py | Add get_retrieval_service without removing existing factories |
| app/rag/retrieval/service.py | Candidate/final limits and dedicated read-session lifecycle |
| app/rag/retrieval/validation.py | Shared query validation |
| app/rag/retrieval/rerankers/{cohere,voyage}_reranker.py | Validate remote responses and sanitize errors |
| app/rag/retrieval/rerankers/http_results.py | Validate indexes/scores; preserve real IDs and citation metadata |
| app/tests/unit/test_retrieval_finalization.py | 18 offline unit tests |
| app/cli/check_retrieval_repository.py | Live owner/status SQL checks with uncommitted, rolled-back fixtures |
| app/cli/check_retrieval.py | Live embedding/retrieval probe, elapsed time, expected-document and unused-owner checks |

App paths are within services/rag-service. The archive stages changes under
refactor/step13/{patches,originals}; extraction itself does not overwrite application
files. scripts/apply_step13.py checks all originals before modifying any file and
creates *.step13.bak backups. It is repeatable and supports --rollback. Keep the
staged originals until this step is accepted.

## 1. Extract and apply (repository root, Git Bash)

```bash
git branch --show-current
git status --short
python scripts/apply_step13.py
source scripts/dc-step12.sh
dc12 config --quiet
```

Expect production-refactor. If the script reports a differing file, it has not changed
any file; send that current file for merging. Do not force replacement over custom
code. Unlike earlier ZIP overlays, use the application script to install these staged
changes rather than copying individual patch files by hand.

## 2. Keep these settings in services/rag-service/.env

```dotenv
RAG_RETRIEVER_BACKEND=hybrid
RAG_DEFAULT_TOP_K=5
RAG_RETRIEVAL_CANDIDATES=20
RAG_RRF_K=60
RAG_RERANKER_ENABLED=false
```

These values are read from the service .env, rather than automatically from the root
.env.compose. Existing remote parser/embedding flags and revision still come from
your Compose overlays/contract.env. Reranking is optional and remains disabled.

Defaults are starting values, not a claim that 20 candidates is optimal for every
dataset. final_top_k is 1..50; configured candidates are 1..100. If top_k exceeds the
configured candidate count, retrieval expands the pool to at least top_k. Pure vector
or keyword retrieval without a reranker fetches only the final result count.

When top_k is missing or null, RAG_DEFAULT_TOP_K controls output consistently, including
when reranking is enabled. RAG_RERANKER_TOP_N remains for compatibility but the search
endpoint uses its final result limit. Existing clients supplying JSON numbers work;
strings like "5" and booleans are now rejected for top_k.

The existing RAG_HYBRID_VECTOR_WEIGHT setting is not used by the current RRF function;
RRF gives each branch equal weight. Do not tune that setting expecting a ranking change.

## 3. Save working image tags, build and run unit checks

On the FIRST build of this step only, retain the current images for rollback:

```bash
docker tag rag-platform/rag-service:local rag-platform/rag-service:step12
docker tag rag-platform/rag-worker:local rag-platform/rag-worker:step12
dc12 build rag-service rag-worker
dc12 run --rm --no-deps rag-service python -m unittest app.tests.unit.test_retrieval_finalization -v
```

Expect 18 tests, OK. Do not repeat the tagging commands after a new image has replaced
:local. This uses the existing dependency lockfiles; uv lock is unnecessary. Both
images must be rebuilt because the shared repository/configuration changed. Running
containers keep the old image until recreated. No paid API calls or model inference
are made by the unit tests.

## 4. Check actual SQL filtering

```bash
dc12 run --rm --no-deps rag-service python -m app.cli.check_retrieval_repository
```

This inserts five temporary documents/chunks inside one transaction, runs actual
vector and full-text SQL, and always rolls back. Cases cover your owner's ingested,
pending, processing and failed documents, plus another owner's ingested document.
Only the first must be returned by both searches. Other connections cannot see these
uncommitted fixtures. It does not publish jobs or touch MinIO/Redis.

It temporarily disables index scans in this session to test exact filtering semantics.
Consequently, this check is NOT a benchmark of your normal HNSW query plan or recall.
Prefer a development database for integration checks. A 30-second statement timeout
prevents an indefinitely slow probe; a timeout requires investigating the database,
not removing owner/status filters.

## 5. Roll out after current ingestion drains

```bash
dc12 stop rag-service
dc12 exec rag-worker python -m app.cli.check_ingestion_drained
```

Keep the existing worker running while pending/processing jobs finish. Repeat the
drain check until it passes. Then:

```bash
dc12 stop rag-worker
dc12 up -d --no-deps --force-recreate rag-worker rag-service
dc12 ps
dc12 logs --tail=100 rag-service rag-worker
dc12 exec rag-service python -m app.cli.check_runtime_image --role api
dc12 exec rag-worker python -m app.cli.check_runtime_image --role worker
dc12 exec rag-service python -m app.tests.integration.check_container_connections --http
```

Supporting services must already be running. The API stays free of model libraries.
No changes to schemas, model revision, stored vectors, Redis streams or MinIO data.

## 6. Check live retrieval for a known uploaded document

Use the authenticated user's UUID and an ingested document belonging to that user.
Replace the uppercase placeholders below; use a short question whose answer is
actually in the document.

```bash
dc12 exec rag-service python -m app.cli.check_retrieval \
  --owner-id USER_UUID \
  --query "A question answered by my test document" \
  --expected-document-id DOCUMENT_UUID \
  --top-k 5
```

The probe checks actual HTTP embedding + retrieval (+ reranking if configured), at
most five results, their owner/ingested status, and no results for an unused owner.
It prints latency and PostgreSQL's installed vector extension version. It performs
no database writes. The explicit owner argument is an administrative test input;
this CLI is not an authentication test and must not become a public endpoint.

Now test POST /api/v1/documents/search in Postman using a valid bearer token:

```json
{"query":"A question answered by my test document","top_k":5}
```

Verify these cases:

1. A known question returns the expected passage/document with real chunk_id,
   document_id and available page/heading metadata.
2. Omit top_k: at most five results with the default settings. top_k=1 returns at most
   one; top_k=50 is supported, while top_k=51 or top_k="5" returns 422.
3. A whitespace-only query returns 422 before embedding/database work.
4. A user with no documents gets results=[]; a second user never sees the first user's
   documents. This must use real auth tokens, in addition to the SQL/CLI checks.
5. Upload/search still works after ingestion reaches ingested. Search sees only fully
   ingested documents; pending/processing/failed records are excluded.
6. Record 10-20 representative questions and their expected passages. Confirm the
   relevant evidence appears in top 5, and measure repeated latency after warmup.

An unrelated question can still return the nearest chunks: vector retrieval always
finds neighbors. results=[] is not a reliable relevance threshold for such questions.
RRF scores are rank-fusion scores, NOT probabilities or cosine similarities. Do not
apply a universal score cutoff. In generation we will handle insufficient evidence
and evaluate grounded answers; calibrated retrieval gating can be added separately.

For outage handling, on your development setup stop embedding-service, issue a vector/
hybrid search, expect a controlled 503, and restore the service immediately:

```bash
dc12 stop embedding-service
# Perform the Postman search; the configured timeout may apply.
dc12 up -d embedding-service
```

Do this with ingestion idle. Pure keyword search intentionally does not call embeddings.

## Performance decisions after measurements

Do not add a Redis retrieval cache yet: cached chunks would need correct invalidation
on document updates/deletions and must remain isolated by owner/model revision.
Remote reranking can be evaluated later; it adds latency and potentially cost.

Check actual SQL plans with EXPLAIN (ANALYZE, BUFFERS) before changing HNSW settings.
The vector ORDER BY distance + LIMIT shape is retained. Owner/status filters may
reduce approximate-index recall; vector index presence alone does not prove sufficient
results or good latency. PostgreSQL pgvector extension version differs from the
Python pgvector dependency version. Iterative scans are available from extension 0.8.0,
but a joined owner filter may require query-plan-specific treatment; do not blindly
enable them or remove authorization predicates. See the primary documentation:
https://github.com/pgvector/pgvector#filtering

## Rollback

Before rolling back, stop API uploads and drain the new worker as in step 5, then stop
it. The rollback checks all changed files before restoring/removing them. It refuses
to overwrite files changed again after applying Step 13.

```bash
python scripts/apply_step13.py --rollback
docker tag rag-platform/rag-service:step12 rag-platform/rag-service:local
docker tag rag-platform/rag-worker:step12 rag-platform/rag-worker:local
dc12 up -d --no-deps --force-recreate rag-worker rag-service
```

There is no database downgrade. Do not delete volumes, source files or model contracts.

## Ready for generation when

All 18 offline checks, live repository checks, runtime checks, actual authenticated
search/isolation and known-passage evaluation pass. Report those results and then
we can start LLM generation using get_retrieval_service, with bounded context,
document/chunk/page citations, insufficient-evidence handling and the SSE token/text
streaming + document-status feature already requested.

Use a fresh dedicated retrieval session. Do not hand RetrievalService a session with
pending writes/active transactions; it deliberately rejects them. Future generation
must end retrieval before holding a streaming LLM connection and use separate short
transactions if conversation persistence is added.

Validation performed here: 18 tests passed using actual Pydantic/HTTPX/SQLAlchemy
libraries, SQL compilation against the RAG models, and mock external transports.
The full current app/auth checkout, Docker and a live PostgreSQL server were not
available here. Real SQL fixture execution, authenticated endpoints, image builds,
HNSW performance and retrieval relevance remain local verification gates.
