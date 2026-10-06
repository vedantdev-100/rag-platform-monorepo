# Step 10: CPU Docling Serve

Branch: production-refactor. API: services/rag-service. Keep one rag-worker.

## Implementation plan

10A (this package): start Docling Serve independently, verify its API and a
representative PDF conversion, and capture its actual package versions/schema.
10B: implement the HTTP DocumentParser adapter and rich-document reconstruction;
verify chunker compatibility, options and failure classification; switch worker
routing only after tests pass. Existing local backend remains a rollback option.
11: BGE ONNX embedding service, used by ingestion and query embeddings; preserve
768 dimensions and test normalization, query prefix and batching parity.
12: slim API/worker images after remote parsing and embedding are verified.
LLM generation stage: implement SSE token streaming and document status events.

## Intended responsibility split

rag-service accepts uploads and exposes status/search. rag-worker owns the
PostgreSQL outbox, Redis ingestion stream, claims/leases/retries, source reads,
chunking/embedding coordination, lifecycle handling and cleanup. Docling Serve
converts bytes over HTTP and returns structured JSON. It is an inference service,
not a second RAG queue worker. Use its local engine; no new Redis broker.

## Files in this package

- docker-compose.docling.yml: new fourth overlay, CPU image pinned to v1.21.0.
- scripts/dc.sh: replaces the helper to include all four overlays.
- docs/STEP10_DOCLING_SERVE.md: this guide.
- docs/RAG_REFACTOR_ROADMAP.md: pending milestones including SSE.

## Apply 10A

Extract into repository root. The image pin is a reproducible initial baseline,
not a claim that this is the latest release or compatible with every client.
No app code, dependencies, database migrations or parser backend changes in 10A.

```bash
source scripts/dc.sh
dc config --quiet
dc pull docling-serve
dc up -d docling-serve
dc ps docling-serve
dc logs --tail=100 docling-serve
```

The CPU image is several GB. Startup warms models and may take minutes. Existing
RAG endpoints continue to use the current parser during this verification stage.
A healthy OpenAPI endpoint confirms the server responds; the conversion test
below confirms the model path works. No host model mount is added: it could hide
models already shipped inside the image. No RAG API rebuild is needed.

## Check from Postman

GET http://127.0.0.1:5001/openapi.json
GET http://127.0.0.1:5001/version

Save both JSON responses for the next adapter step. OpenAPI is authoritative for
this pinned deployment. For a direct PDF conversion:

POST http://127.0.0.1:5001/v1/convert/file
Body -> form-data:
- files: File -> choose a small representative PDF.
- to_formats: Text -> json.
- do_ocr: Text -> true (or your current setting).
- do_table_structure: Text -> true (or your current setting).

Let Postman set the multipart Content-Type boundary automatically. Allow up to
15 minutes request timeout for this check. Expect a successful conversion with
structured Docling JSON, not merely markdown. Check tables, reading order and
page metadata on your actual documents. Keep the returned JSON for the adapter
compatibility test. Compare picture-description options separately if currently
enabled; do not silently discard them during migration.

## Check connectivity from worker

```bash
dc exec rag-worker python -c "import urllib.request; print(urllib.request.urlopen('http://docling-serve:5001/openapi.json', timeout=10).status)"
```

Expected: 200. The worker uses docling-serve:5001; host/Postman uses 127.0.0.1:5001.
The host binding is local only. Remove it after verification if not needed.

## Required inputs for 10B

Provide current files (especially if modified since Step 9):
- services/rag-service/app/rag/ingestion/chunking/docling_chunker.py
- services/rag-service/app/rag/ingestion/chunking/tokenizers.py
- services/rag-service/pyproject.toml
- Docling Serve GET /version and GET /openapi.json responses.
- JSON response from the direct PDF conversion (a small non-sensitive sample).

Already available: current parser, Step 9 factory/workflows/config baseline.
Send modified versions if you changed these. No secrets or .env contents needed.

## Adapter acceptance criteria (10B)

The adapter must return ParsedDocument with native DoclingDocument compatible
with the existing hybrid chunker. Preserve tables/headings/page references and
picture descriptions when enabled. Preserve txt-to-md filename normalization.
Use bounded timeouts and the existing attempt lease/heartbeat; classify transport
errors as retryable and confirmed invalid document errors as terminal. Check
server conversion status even for HTTP 200. Record parser provider/version and
update processing fingerprint in API and worker together; drain old queued jobs
before a fingerprint-changing rollout. Never call remote parsing inside a DB
transaction. Verify deletion during conversion cannot restore deleted data.

Acceptance: PDF/DOCX/PPTX/HTML/MD/TXT uploads reach ingested and remain searchable;
structured metadata is retained; service outage triggers bounded retries; user
delete still cleans source and DB; queue probe still passes. Only then switch
RAG_PARSER_BACKEND and recreate API/worker together. Dependencies are slimmed later.

## Verification performed here

Compose YAML and shell syntax checked locally. Docker pull, model startup,
network calls and real PDF conversion need execution on your machine.

## Official references

https://github.com/docling-project/docling-serve/blob/v1.21.0/README.md
https://github.com/docling-project/docling-serve/blob/v1.21.0/docs/configuration.md
https://github.com/docling-project/docling-serve/blob/v1.21.0/docs/usage.md
