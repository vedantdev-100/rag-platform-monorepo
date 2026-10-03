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

    async def revoke(self, jti: str, ttl_seconds: int) -> None:
        # TTL = remaining token lifetime, so the key auto-expires exactly
        # when the token would have expired anyway — no manual cleanup needed.
        await self._redis.set(f"revoked:{jti}", "1", ex=ttl_seconds)
 