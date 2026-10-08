"""
Voyage AI's hosted rerank API (https://api.voyageai.com/v1/rerank). Same
security note as CohereReranker: sends chunk text off this machine.
"""
import httpx

from app.exceptions import RetrievalError
from app.rag.retrieval.base import Reranker, RetrievedChunk

_ENDPOINT = "https://api.voyageai.com/v1/rerank"


class VoyageReranker(Reranker):
    def __init__(self, api_key: str, model: str, timeout: int = 30):
        self._api_key = api_key
        self._model = model
        self._timeout = timeout

    async def rerank(
        self, query: str, chunks: list[RetrievedChunk], *, top_n: int | None = None
    ) -> list[RetrievedChunk]:
        if not chunks:
            return []
        payload = {
            "model": self._model,
            "query": query,
            "documents": [chunk.content for chunk in chunks],
            "top_k": top_n or len(chunks),
        }
        headers = {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(_ENDPOINT, json=payload, headers=headers)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise RetrievalError(f"Voyage rerank request failed: {exc}") from exc

        results = response.json()["data"]  # already sorted by relevance_score desc
        return [
            RetrievedChunk(**{**chunks[r["index"]].__dict__, "score": r["relevance_score"]})
            for r in results
        ]