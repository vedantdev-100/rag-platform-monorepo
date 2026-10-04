"""
Per-user revocation check: a timestamp, not a per-token jti set. Chosen
specifically because deactivate/delete are admin-initiated against a
target user who isn't the one making the request - there's no token in
hand to blacklist by jti. Storing "reject anything issued before T" kills
every token that user currently holds (any device, any session) in one
write, which is also exactly right for deactivate/delete: ALL of that
user's access should die at once, not just one session's.
"""

from datetime import datetime, timezone

from platform_auth.config import PlatformAuthSettings


class TokenBlacklist:
    def __init__(self, settings: PlatformAuthSettings):
        if not settings.REDIS_URL:
            self._redis = None
            return
        import redis.asyncio as redis
        self._redis = redis.from_url(settings.REDIS_URL)
        # Used as the TTL on the revocation marker — no point keeping it
        # around longer than the longest-lived token it could possibly reject.
        self._max_token_lifetime_seconds = settings.MAX_TOKEN_LIFETIME_SECONDS

    def _key(self, user_id: str) -> str:
        return f"revoked_users:{user_id}"

    async def revoke_user(self, user_id: str) -> None:
        """Call this at the moment a user is logged out / deactivated / deleted."""
        if self._redis is None:
            return
        now = datetime.now(timezone.utc).timestamp()
        await self._redis.set(self._key(user_id), now, ex=self._max_token_lifetime_seconds)

    async def is_token_revoked(self, user_id: str, issued_at: float) -> bool:
        """issued_at is the token's `iat` claim (unix timestamp)."""
        if self._redis is None:
            return False
        revoked_at = await self._redis.get(self._key(user_id))
        if revoked_at is None:
            return False
        return issued_at < float(revoked_at)
    
# """
# Instant-revocation check: on logout/refresh, auth-service writes the
# old token's jti to this Redis set (TTL = remaining token lifetime).
# Every consuming service checks it here before trusting an otherwise-
# valid token.
# """
# from platform_auth.config import PlatformAuthSettings


# class TokenBlacklist:
#     def __init__(self, settings: PlatformAuthSettings):
#         if not settings.REDIS_URL:
#             self._redis = None
#             return
#         import redis.asyncio as redis
#         self._redis = redis.from_url(settings.REDIS_URL)

#     async def is_revoked(self, jti: str) -> bool:
#         if self._redis is None:
#             return False  # blacklist not  accept token as valid
#         return bool(await self._redis.exists(f"revoked:{jti}"))

#     async def revoke(self, jti: str, ttl_seconds: int) -> None:
#         # TTL = remaining token lifetime, so the key auto-expires exactly
#         # when the token would have expired anyway — no manual cleanup needed.
#         await self._redis.set(f"revoked:{jti}", "1", ex=ttl_seconds)
 