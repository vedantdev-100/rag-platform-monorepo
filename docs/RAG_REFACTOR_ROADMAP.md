# RAG refactor roadmap

| Stage | State |
| --- | --- |
| 9: one worker, durable Redis/outbox ingestion, retries and status | User verified |
| 10B: remote Docling Serve parsing and structured chunking | User verified |
| 11: shared CPU ONNX embeddings for documents/queries | User reports uploads and endpoints working |
| 12: separate slim API and worker images | Setup supplied; local image builds and endpoint verification required |
| LLM generation and SSE | Deferred: token/text streaming and document status events required by user |

Keep services/rag-service, branch production-refactor, one rag-worker and external
GitHub platform-auth dependency. Preserve the database schemas, vector(768), embedding
contract and current chunking behavior. Kubernetes remains deferred. SSE belongs in
the later LLM generation step; this packaging step does not implement it.
