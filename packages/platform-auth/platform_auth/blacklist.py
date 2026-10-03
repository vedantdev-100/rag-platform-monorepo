"""
Instant-revocation check: on logout/refresh, auth-service writes the
old token's jti to this Redis set (TTL = remaining token lifetime).
Every consuming service checks it here before trusting an otherwise-
valid token.
"""
from platform_auth.config import PlatformAuthSettings


class TokenBlacklist:
    def __init__(self, settings: PlatformAuthSettings):
        if not settings.REDIS_URL:
            self._redis = None
            return
        import redis.asyncio as redis
        self._redis = redis.from_url(settings.REDIS_URL)

    async def is_revoked(self, jti: str) -> bool:
        if self._redis is None:
            return False  # blacklist not  accept token as valid
        return bool(await self._redis.exists(f"revoked:{jti}"))
 