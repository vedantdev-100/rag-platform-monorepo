"""
Real embeddings via sentence-transformers (default: BAAI/bge-base-en-v1.5),
loaded from a LOCAL folder under MODELS_DIR — populated by
`uv run python -m app.cli.download_models`. Nothing is downloaded at
runtime, so the service starts and runs with no internet access.

Inference is synchronous and CPU/GPU-bound (sentence-transformers has no
async API), so it runs in a worker thread instead of blocking the event
loop that is serving other requests.
"""
import asyncio
from pathlib import Path

from app.rag.ingestion.base import EmbeddingGenerator


class SentenceTransformersEmbedder(EmbeddingGenerator):
    def __init__(
        self,
        model_path: str | Path,
        dimensions: int,
        batch_size: int = 32,
        device: str | None = None,
    ):
        # Imported here, not at module level, so code that only needs the
        # interface or the stub backend doesn't pay the torch import cost.
        from sentence_transformers import SentenceTransformer

        self._model = SentenceTransformer(str(model_path), device=device or None)
        actual = self._model.get_sentence_embedding_dimension()
        if actual != dimensions:
            # pgvector's column is fixed-width (vector(768)); a mismatch
            # would otherwise surface later as a confusing insert error.
            raise ValueError(
                f"Embedding model at {model_path} outputs {actual}-dim vectors but "
                f"EMBEDDING_DIMENSIONS={dimensions} (the database column width)"
            )
        self._dimensions = dimensions
        self._batch_size = batch_size

    @property
    def dimensions(self) -> int:
        return self._dimensions

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        # normalize_embeddings=True: bge models are trained for cosine
        # similarity on normalized vectors — matches
        # ChunkRepository.similarity_search()'s cosine_distance() and the
        # vector_cosine_ops HNSW index.
        embeddings = await asyncio.to_thread(
            self._model.encode,
            texts,
            batch_size=self._batch_size,
            normalize_embeddings=True,
        )
        return [vector.tolist() for vector in embeddings]
