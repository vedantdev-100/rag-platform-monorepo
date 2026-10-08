from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    top_k: int | None = Field(default=None, ge=1, le=50)


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