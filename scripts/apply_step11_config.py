"""Preserve existing config/search changes; add settings and 503 handling."""
import ast
from pathlib import Path
config=Path('services/rag-service/app/core/config.py')
search=Path('services/rag-service/app/api/v1/endpoints/search.py')
c=config.read_text(encoding="utf-8");s=search.read_text(encoding="utf-8")
marker='    # Step 11: shared embedding contract.\n'
if marker not in c:
    old='    RAG_EMBEDDING_BACKEND: Literal["stub", "sentence_transformers"] = "sentence_transformers"'
    if c.count(old)!=1:raise SystemExit('Embedding backend declaration changed; send current config.py')
    c=c.replace(old,'''    RAG_EMBEDDING_BACKEND: Literal["stub", "sentence_transformers", "http"] = "sentence_transformers"
    # Step 11: shared embedding contract.
    EMBEDDING_SERVICE_URL: str = "http://embedding-service:8000"
    EMBEDDING_SERVICE_REVISION: str = ""
    EMBEDDING_SERVICE_API_KEY: SecretStr = SecretStr("")
    EMBEDDING_SERVICE_TIMEOUT_SECONDS: int = 75

    @model_validator(mode="after")
    def _validate_embedding_service(self) -> "Settings":
        if self.RAG_EMBEDDING_BACKEND != "http":return self
        import re
        from urllib.parse import urlsplit
        url=urlsplit(self.EMBEDDING_SERVICE_URL)
        if (url.scheme not in {"http","https"} or not url.netloc or url.path not in {"","/"}
                or url.username or url.password or url.query or url.fragment):
            raise ValueError("EMBEDDING_SERVICE_URL must be a server URL without credentials")
        if not re.fullmatch(r"bge-onnx-v1:[0-9a-f]{64}",self.EMBEDDING_SERVICE_REVISION):
            raise ValueError("Generate the Step 11 model contract before enabling HTTP embeddings")
        if self.RAG_EMBEDDING_MODEL!="BAAI/bge-base-en-v1.5" or self.EMBEDDING_DIMENSIONS!=768:
            raise ValueError("Step 11 model contract requires BGE base en v1.5 and dimension 768")
        if not 65 <= self.EMBEDDING_SERVICE_TIMEOUT_SECONDS < self.INGESTION_JOB_TIMEOUT_SECONDS:
            raise ValueError("Embedding timeout must be >=65 seconds and below the job timeout")
        return self
'''.rstrip())
if 'from app.rag.embeddings.client import EmbeddingServiceError' not in s:
    old='    results = await retriever.retrieve(payload.query, owner_id=str(current_user.id), top_k=candidate_count)'
    if s.count(old)!=1:raise SystemExit('Search retrieval call changed; send current search.py')
    s=s.replace(old,'''    try:
        results = await retriever.retrieve(payload.query, owner_id=str(current_user.id), top_k=candidate_count)
    except EmbeddingServiceError:
        raise HTTPException(status_code=503, detail="embedding_service_unavailable")''')
    s='from fastapi import HTTPException\nfrom app.rag.embeddings.client import EmbeddingServiceError\n'+s
ast.parse(c);ast.parse(s)
for path,new in ((config,c),(search,s)):
    if path.read_text(encoding="utf-8")!=new:
        backup=path.with_suffix('.py.step11.bak')
        if not backup.exists():backup.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        path.write_text(new, encoding="utf-8")
print('Step 11 settings and search error handling applied')
