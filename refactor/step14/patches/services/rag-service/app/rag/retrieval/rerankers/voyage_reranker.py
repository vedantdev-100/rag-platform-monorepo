"""
Voyage AI's hosted rerank API (https://api.voyageai.com/v1/rerank). Same
security note as CohereReranker: sends chunk text off this machine.
"""
import httpx

from app.exceptions import RetrievalError
from app.rag.retrieval.base import Reranker, RetrievedChunk
from app.rag.retrieval.rerankers.http_results import parse_results

_ENDPOINT = "https://api.voyageai.com/v1/rerank"


class VoyageReranker(Reranker):
    def __init__(self, api_key: str, model: str, timeout: int = 30, *, transport=None):
        self._api_key = api_key
        self._model = model
        self._timeout = timeout
        self._transport = transport

    async def rerank(
        self, query: str, chunks: list[RetrievedChunk], *, top_n: int | None = None
    ) -> list[RetrievedChunk]:
        if not chunks:
            return []
        limit = min(top_n or len(chunks), len(chunks))
        payload = {
            "model": self._model,
            "query": query,
            "documents": [chunk.content for chunk in chunks],
            "top_k": limit,
        }
        headers = {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}

        try:
            async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
                response = await client.post(_ENDPOINT, json=payload, headers=headers)
                response.raise_for_status()
            return parse_results(response.json(), "data", chunks, limit)
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            raise RetrievalError("Reranking service unavailable or returned an invalid response") from exc
