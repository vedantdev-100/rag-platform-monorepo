from pydantic import BaseModel, Field, field_validator

from app.rag.retrieval.validation import normalize_query


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    top_k: int | None = Field(default=None, ge=1, le=50, strict=True)

    @field_validator("query")
    @classmethod
    def meaningful_query(cls, query: str) -> str:
        return normalize_query(query)


class SearchResultOut(BaseModel):
    chunk_id: str
    document_id: str
    content: str
    score: float
    modality: str
    metadata: dict


class SearchResponse(BaseModel):
    query: str
    results: list[SearchResultOut]
    retriever_backend: str
    reranked: bool
