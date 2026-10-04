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

    # TTL for the revocation marker in Redis. Set this to the longest
    # possible token lifetime in your system (access token expiry is enough
    # today; if you ever add long-lived service tokens, use the longest of
    # all token types here).
    MAX_TOKEN_LIFETIME_SECONDS: int = 900  # match ACCESS_TOKEN_EXPIRE_MINUTES=15 default
