from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.rag.generation.types import Answer
from app.rag.retrieval.validation import normalize_query


class GenerationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1, max_length=2000)
    top_k: int | None = Field(None, strict=True, ge=1, le=50)

    @field_validator("query")
    @classmethod
    def clean_query(cls, value):
        return normalize_query(value)


GenerationResponse = Answer
