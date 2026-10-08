# Step 14 verification

Built against rag_step14_current_source.zip, not an unseen GitHub checkout.
Verified on Python 3.12.14 using the regenerated uv.lock and API generation/dev extras.

- 69 offline tests passed: generation graphs, input/context bounds, citation and
  completion validation, no-evidence/provider abstention, provider protocols and SSE
  framing, usage frames, HTTP/midstream failures, optional fallback, capacity/deadline,
  bounded queues, real ASGI disconnect, HTTP response cancellation/closure, actual
  platform-auth dependency/blacklist wiring with mock transport, document status and
  ownership/session closure, and retrieval SQL predicates/transaction lifecycle.
- Four scripted contract-harness cases passed. These are not model-quality evidence.
- New end-to-end harness request sequencing and stop-on-error behavior tested with
  HTTP fixtures; no live upload or hosted call made from this environment.
- uv lock succeeded; uv sync --locked --extra generation succeeded. Framework pins
  respect the existing seven-day exclusion policy; original Pydantic/FastAPI/httpx
  pins remain. LangGraph 1.2.12, langchain-core 1.6.6.
- API dependency gate passed: no PyTorch/Docling converter/ONNX runtime or worker
  tokenizer stack installed. Worker locked dependency export excludes LangGraph/core.
- Disabled and enabled API startup/shutdown checked without DB/Redis/provider calls.
  For enabled-client creation, test-environment SOCKS proxy variables were removed:
  the existing httpx 0.27.2 does not accept socks5h proxy URLs. Application transport
  configuration was not changed to bypass a deployment's intentional proxy.
- Ruff undefined-name/unused-import checks passed for new code; shell script syntax
  passed. Patch Python/TOML/lock payloads parsed before staging.
- Guarded preflight, apply, second apply (zero changes), rollback and rejection of
  a custom router edit without any patch writes tested on a separate source copy.

One existing framework warning remains: Starlette 0.38.6 imports the multipart alias,
which emits PendingDeprecationWarning with the pinned multipart package. It does not
fail these checks; dependency upgrades are outside this generation step.

Not verified here: Docker image builds, live PostgreSQL/Redis/MinIO/Docling/embedding
connectivity, ingestion duration, hosted-provider availability/quotas/answer quality,
frontend rendering, or reverse-proxy streaming. Follow STEP14_GENERATION.md on your
running setup before marking Step 14 accepted. Live harness calls consume provider
quota and leave their test document for inspection.
