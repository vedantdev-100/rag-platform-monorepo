from functools import lru_cache
from pathlib import Path
from typing import List, Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    APP_NAME: str = "auth-service"
    ENVIRONMENT: Literal["development", "staging", "production"] = "development"
    DEBUG: bool = False
    API_V1_PREFIX: str = "/api/v1"
    ALLOWED_ORIGINS: List[str] = ["http://localhost:3000"]

    DATABASE_URL: str

    JWT_PRIVATE_KEY_PATH: str
    JWT_PUBLIC_KEY_PATH: str
    JWT_ALGORITHM: str = "RS256"
    JWT_KEY_ID: str = "2026-01"  # bump when rotating; must appear in /.well-known/jwks.json
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    BCRYPT_ROUNDS: int = 12
    RATE_LIMIT_LOGIN: str = "5/minute"
    RATE_LIMIT_REGISTER: str = "3/minute"
    RATE_LIMIT_REFRESH: str = "10/minute"
    RATE_LIMIT_LOGOUT: str = "10/minute"
    RATE_LIMIT_DEFAULT: str = "60/minute"

    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_POOL_TIMEOUT: int = 30
    DB_POOL_RECYCLE: int = 1800

    @property
    def jwt_private_key(self) -> str:
        return Path(self.JWT_PRIVATE_KEY_PATH).read_text()

    @property
    def jwt_public_key(self) -> str:
        return Path(self.JWT_PUBLIC_KEY_PATH).read_text()

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
