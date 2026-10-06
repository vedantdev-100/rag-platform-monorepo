# RAG refactor roadmap

2026-10-06: user reports Step 9 upload and all endpoints functional.

| Stage | Work | State |
| --- | --- | --- |
| 9 | Single worker with durable ingestion outbox, Redis stream, retries and status polling | User verified |
| 10A | CPU Docling Serve deployment and conversion check | Running versions and OpenAPI supplied by user |
| 10B | Worker HTTP parser adapter and chunker/schema compatibility | Patch supplied; real probe and rollout pending |
| 11 | Shared BGE base en v1.5 ONNX embedding service, CPU batching | Planned |
| 12 | Slim runtime images and deployment validation | Planned |
| LLM generation | Live SSE token streaming and document status events | Required by user |

## SSE requirement

Implement when adding LLM generation. Stream token/text deltas to the frontend
so responses appear incrementally; chunks may contain parts of words or multiple
words. Add document status events to replace active polling where appropriate.
Define done/error events, authentication and owner scoping, disconnect cancellation,
proxy buffering/timeout behavior and reconnect behavior. Generation streaming is
not automatically resumable; document status can resynchronize through GET.
For POST generation with Bearer auth, consider fetch response streaming: native
EventSource does not support arbitrary auth headers or POST bodies. Keep polling
as a fallback for document status. SSE is planned, not implemented in Step 10.

## Fixed decisions

Keep services/rag-service and branch production-refactor. Keep platform-auth as
a GitHub dependency. Keep one rag-worker. PostgreSQL schemas rag/auth and existing
Redis roles remain. Use MinIO for sources. CPU deployment; defer Kubernetes.
