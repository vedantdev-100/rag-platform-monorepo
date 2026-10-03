from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class PlatformAuthSettings(BaseSettings):
    # model_config = SettingsConfigDict(env_prefix="PLATFORM_AUTH_", extra="ignore")
    model_config = SettingsConfigDict(env_prefix="PLATFORM_AUTH_", env_file=".env", extra="ignore")

    JWKS_URL: str = Field(..., description="e.g. http://auth-service/.well-known/jwks.json")
    JWKS_CACHE_TTL_SECONDS: int = 900  # 15 min
    JWT_ALGORITHM: str = "RS256"

    # Optional: enables instant-revocation checks (needs the [redis] extra).
    REDIS_URL: str | None = None
