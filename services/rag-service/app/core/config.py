"""
No JWT_* fields at all  rag-service never issues or holds signing
keys. Token verification settings (PLATFORM_AUTH_JWKS_URL, etc.) live
in platform_auth's own PlatformAuthSettings, read from the same .env
via the PLATFORM_AUTH_ env prefix.
"""
from functools import lru_cache
from typing import List, Literal

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    APP_NAME: str = "rag-service"
    ENVIRONMENT: Literal["development", "staging", "production"] = "development"
    DEBUG: bool = False
    API_V1_PREFIX: str = "/api/v1"
    ALLOWED_ORIGINS: List[str] = ["http://localhost:3000"]

    DATABASE_URL: str

    RATE_LIMIT_UPLOAD: str = "5/minute"
    RATE_LIMIT_SEARCH: str = "20/minute"
    RATE_LIMIT_DEFAULT: str = "60/minute"

    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_POOL_TIMEOUT: int = 30
    DB_POOL_RECYCLE: int = 1800

    REDIS_URL: str = "redis://localhost:6379/0"
    USER_EVENTS_STREAM: str = "user-events"
    USER_EVENTS_CONSUMER_GROUP: str = "rag-service"

    STORAGE_BACKEND: Literal["local"] = "local"
    LOCAL_STORAGE_DIR: str = "./data/uploads"
    RAG_MAX_UPLOAD_MB: int = 25
    MODELS_DIR: str = "./models"

    RAG_PARSER_BACKEND: Literal["docling"] = "docling"
    RAG_PARSER_MAX_CONCURRENCY: int = 1
    RAG_DOCLING_LOCAL_MODELS_ONLY: bool = True
    RAG_OCR_ENABLED: bool = True
    RAG_TABLE_STRUCTURE_ENABLED: bool = True

    RAG_PICTURE_DESCRIPTION_ENABLED: bool = False
    RAG_PICTURE_DESCRIPTION_BACKEND: Literal["local", "api"] = "local"
    RAG_PICTURE_DESCRIPTION_MODEL: str = "HuggingFaceTB/SmolVLM-256M-Instruct"
    RAG_PICTURE_DESCRIPTION_PROMPT: str = (
        "Describe this image in a few sentences. If it is a chart, graph or diagram, "
        "state its type, axes, series, and the key values and trends."
    )
    RAG_PICTURE_MIN_AREA: float = 0.05
    RAG_PICTURE_DESCRIPTION_API_URL: str = ""
    RAG_PICTURE_DESCRIPTION_API_MODEL: str = ""
    RAG_PICTURE_DESCRIPTION_API_KEY: SecretStr = SecretStr("")
    RAG_PICTURE_DESCRIPTION_TIMEOUT: int = 60

    RAG_CHUNKER_BACKEND: Literal["docling", "simple"] = "docling"
    RAG_CHUNKER_TOKENIZER: Literal["huggingface", "approx"] = "huggingface"
    RAG_CHUNKER_TOKENIZER_MODEL: str = "BAAI/bge-base-en-v1.5"
    RAG_CHUNKER_MAX_TOKENS: int = 500
    RAG_CHUNKER_MERGE_PEERS: bool = True

    RAG_EMBEDDING_BACKEND: Literal["stub", "sentence_transformers"] = "sentence_transformers"
    RAG_EMBEDDING_MODEL: str = "BAAI/bge-base-en-v1.5"
    RAG_EMBEDDING_DEVICE: str | None = None
    RAG_EMBEDDING_BATCH_SIZE: int = 32
    EMBEDDING_DIMENSIONS: int = 768

    RAG_DEFAULT_TOP_K: int = 5
    RAG_CHUNK_SIZE: int = 512
    RAG_CHUNK_OVERLAP: int = 50
    RAG_DISTANCE_METRIC: str = "cosine"
    RAG_HYBRID_VECTOR_WEIGHT: float = 0.5

    RAG_RETRIEVER_BACKEND: Literal["vector", "keyword", "hybrid"] = "hybrid"
    RAG_RETRIEVAL_CANDIDATES: int = 20
    RAG_RRF_K: int = 60

    RAG_RERANKER_ENABLED: bool = False
    RAG_RERANKER_BACKEND: Literal["local", "api"] = "local"
    RAG_RERANKER_TOP_N: int = 5
    RAG_RERANKER_MODEL: str = "BAAI/bge-reranker-base"
    RAG_RERANKER_DEVICE: str | None = None
    RAG_RERANKER_API_PROVIDER: Literal["cohere", "voyage"] = "cohere"
    RAG_RERANKER_API_KEY: SecretStr = SecretStr("")
    RAG_RERANKER_API_MODEL: str = "rerank-english-v3.0"
    RAG_RERANKER_API_TIMEOUT: int = 30

    @model_validator(mode="after")
    def _validate_picture_description(self) -> "Settings":
        if self.RAG_PICTURE_DESCRIPTION_ENABLED and self.RAG_PICTURE_DESCRIPTION_BACKEND == "api":
            missing = [n for n in ("RAG_PICTURE_DESCRIPTION_API_URL", "RAG_PICTURE_DESCRIPTION_API_MODEL") if not getattr(self, n)]
            if missing:
                raise ValueError(f"RAG_PICTURE_DESCRIPTION_BACKEND=api requires: {', '.join(missing)}")
        return self

    @model_validator(mode="after")
    def _validate_reranker(self) -> "Settings":
        if self.RAG_RERANKER_ENABLED and self.RAG_RERANKER_BACKEND == "api":
            if not self.RAG_RERANKER_API_KEY.get_secret_value():
                raise ValueError("RAG_RERANKER_BACKEND=api requires RAG_RERANKER_API_KEY")
        return self

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
