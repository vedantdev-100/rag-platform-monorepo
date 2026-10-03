"""
Deterministic placeholder embeddings — content-hash-seeded, NOT semantically
meaningful. Exists purely so the ingestion pipeline, storage, and hybrid
search can be built and tested end-to-end (including real pgvector inserts
and similarity queries) before a real embedding model is wired in. Never
use this for anything beyond wiring/integration tests: similarity search
results against these vectors are meaningless.
"""
import hashlib
import random

from app.rag.ingestion.base import EmbeddingGenerator


class StubEmbeddingGenerator(EmbeddingGenerator):
    def __init__(self, dimensions: int = 768):
        self._dimensions = dimensions

    @property
    def dimensions(self) -> int:
        return self._dimensions

    async def embed(self, texts: list[str]) -> list[list[float]]:
        vectors = []
        for text in texts:
            seed = int(hashlib.sha256(text.encode()).hexdigest(), 16) % (2**32)
            rng = random.Random(seed)
            vectors.append([rng.uniform(-1, 1) for _ in range(self._dimensions)])
        return vectors
