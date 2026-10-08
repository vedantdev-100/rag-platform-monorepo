"""Validate remote ordering without allowing invented/duplicate chunk references."""
from dataclasses import replace
import math

from app.rag.retrieval.base import RetrievedChunk


def parse_results(payload, key: str, chunks: list[RetrievedChunk], limit: int) -> list[RetrievedChunk]:
    if not isinstance(payload, dict) or not isinstance(payload.get(key), list):
        raise ValueError("Invalid reranking response")
    rows = payload[key]
    if len(rows) > limit:
        raise ValueError("Too many reranking results")
    used, results = set(), []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Invalid reranking result")
        index, score = row.get("index"), row.get("relevance_score")
        if (isinstance(index, bool) or not isinstance(index, int)
                or not 0 <= index < len(chunks) or index in used
                or isinstance(score, bool) or not isinstance(score, (int, float))):
            raise ValueError("Invalid reranking index/score")
        try:
            score = float(score)
        except OverflowError as exc:
            raise ValueError("Invalid reranking score") from exc
        if not math.isfinite(score):
            raise ValueError("Invalid reranking score")
        used.add(index)
        results.append(replace(chunks[index], score=float(score)))
    # Both providers document descending order; sorting also makes this explicit.
    return sorted(results, key=lambda chunk: chunk.score, reverse=True)
