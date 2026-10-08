from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class GenerationSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    RAG_RUNTIME_ROLE: Literal["development", "api", "worker"] = "development"
    RAG_GENERATION_ENABLED: bool = False
    RAG_GENERATION_STRATEGY: Literal["standard"] = "standard"
    RAG_LLM_PROVIDER: Literal["openrouter", "groq", "openai"] = "openrouter"
    OPENROUTER_API_KEY: SecretStr = SecretStr("")
    OPENROUTER_MODEL: str = ""
    GROQ_API_KEY: SecretStr = SecretStr("")
    GROQ_MODEL: str = ""
    OPENAI_API_KEY: SecretStr = SecretStr("")
    OPENAI_MODEL: str = ""
    RAG_LLM_FREE_ONLY: bool = True
    RAG_LLM_FALLBACK_ENABLED: bool = False
    RAG_LLM_FALLBACK_PROVIDER: Literal["openrouter", "groq", "openai"] | None = None
    RAG_LLM_MAX_OUTPUT_TOKENS: int = Field(512, ge=32, le=8192)
    RAG_LLM_TIMEOUT_SECONDS: int = Field(90, ge=10, le=300)
    RAG_LLM_MAX_CONCURRENT: int = Field(2, ge=1, le=32)
    # Per process; add a Redis concurrency coordinator before scaling replicas.
    RATE_LIMIT_GENERATION: str = "5/minute"
    RATE_LIMIT_DOCUMENT_EVENTS: str = "10/minute"
    RAG_CONTEXT_MAX_BYTES: int = Field(12000, ge=2000, le=100000)
    RAG_CONTEXT_MAX_CHUNKS: int = Field(5, ge=1, le=20)
    RAG_SSE_HEARTBEAT_SECONDS: int = Field(10, ge=1, le=30)
    RAG_SSE_QUEUE_SIZE: int = Field(32, ge=1, le=128)
    RAG_DOCUMENT_EVENTS_POLL_SECONDS: int = Field(3, ge=1, le=30)
    RAG_DOCUMENT_EVENTS_MAX_SECONDS: int = Field(300, ge=10, le=900)
    RAG_DOCUMENT_EVENTS_MAX_CONCURRENT: int = Field(10, ge=1, le=100)

    @property
    def active(self):
        return self.RAG_GENERATION_ENABLED and self.RAG_RUNTIME_ROLE != "worker"

    @property
    def model(self):
        return getattr(self, self.RAG_LLM_PROVIDER.upper() + "_MODEL").strip()

    @property
    def api_key(self):
        return getattr(
            self, self.RAG_LLM_PROVIDER.upper() + "_API_KEY"
        ).get_secret_value()

    @model_validator(mode="after")
    def validate_provider(self):
        if self.active:
            if not self.api_key or not self.model or len(self.model) > 200:
                raise ValueError(
                    "Enabled generation requires its selected provider key and model"
                )
            if self.RAG_LLM_FREE_ONLY:
                if self.RAG_LLM_PROVIDER == "openai":
                    raise ValueError("OpenAI requires explicit RAG_LLM_FREE_ONLY=false")
                if self.RAG_LLM_PROVIDER == "openrouter" and not (
                    self.model.endswith(":free") or self.model == "openrouter/free"
                ):
                    raise ValueError(
                        "Free-only OpenRouter requires a :free model or openrouter/free"
                    )
            if self.RAG_LLM_FALLBACK_ENABLED:
                alternate = self.RAG_LLM_FALLBACK_PROVIDER
                if alternate is None or alternate == self.RAG_LLM_PROVIDER:
                    raise ValueError(
                        "Fallback requires a different configured provider"
                    )
                copy = self.model_copy(
                    update={
                        "RAG_LLM_PROVIDER": alternate,
                        "RAG_LLM_FALLBACK_ENABLED": False,
                    }
                )
                copy.validate_provider()
        return self


@lru_cache
def get_generation_settings():
    return GenerationSettings()
