from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol, TypedDict

from pydantic import BaseModel, Field

from app.rag.retrieval.base import RetrievedChunk


class Source(BaseModel):
    label: str
    document_id: str
    chunk_id: str
    modality: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class Answer(BaseModel):
    request_id: str
    status: str
    answer: str
    sources: list[Source]
    provider: str
    model: str
    usage: dict[str, int] | None = None
    query_resolution_usage: dict[str, int] | None = None


@dataclass
class ProviderResult:
    text: str = ""
    usage: dict[str, int] | None = None
    finish_reason: str | None = None
    model: str | None = None
    provider: str | None = None


Emit = Callable[[str, dict], Awaitable[None]]


class EvidenceRetriever(Protocol):
    async def retrieve(
        self, query: str, *, owner_id: str, top_k: int | None
    ) -> list[RetrievedChunk]: ...


class Provider(Protocol):
    async def generate(self, messages: list[dict], emit: Emit) -> ProviderResult: ...
    async def close(self): ...


class GraphState(TypedDict, total=False):
    query: str
    retrieval_query: str
    query_resolution_usage: dict[str, int] | None
    history: list[dict]
    document_ids: list | None
    thread_id: str
    owner_id: str
    top_k: int | None
    request_id: str
    chunks: list[RetrievedChunk]
    sources: list[Source]
    messages: list[dict]
    result: ProviderResult
    answer: Answer


class GenerationError(Exception):
    def __init__(
        self,
        code="generation_unavailable",
        status=503,
        retryable=False,
        retry_after=None,
    ):
        super().__init__(code)
        self.code, self.status, self.retryable, self.retry_after = (
            code,
            status,
            retryable,
            retry_after,
        )
