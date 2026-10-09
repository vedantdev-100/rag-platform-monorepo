from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

class ChatSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')
    RAG_CHAT_HISTORY_MAX_MESSAGES: int = Field(12, ge=2, le=40)
    RAG_CHAT_HISTORY_MAX_BYTES: int = Field(6000, ge=1000, le=20000)
    RAG_CHAT_LEASE_SECONDS: int = Field(30, ge=15, le=120)
    RAG_CHAT_MAX_DOCUMENTS: int = Field(100, ge=1, le=500)
    RATE_LIMIT_CHAT_MUTATION: str = '30/minute'

@lru_cache
def get_chat_settings():
    return ChatSettings()
