"""
Fetches and caches auth-service's public signing keys by `kid`. This is
what makes key rotation dynamic: auth-service can add a new key without
any consuming service being redeployed the cache just misses once,
refetches, and picks up the new key.
"""
import time

import httpx

from platform_auth.config import PlatformAuthSettings
from platform_auth.exceptions import InvalidTokenError


class JWKSClient:
    def __init__(self, settings: PlatformAuthSettings):
        self._settings = settings
        self._keys: dict[str, dict] = {}
        self._fetched_at: float = 0.0

    async def _refresh(self) -> None:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.get(self._settings.JWKS_URL)
            response.raise_for_status()
        self._keys = {key["kid"]: key for key in response.json()["keys"]}
        self._fetched_at = time.monotonic()

    async def get_key(self, kid: str | None) -> dict:
        if kid is None:
            raise InvalidTokenError("Token has no key ID (kid)")

        stale = (time.monotonic() - self._fetched_at) > self._settings.JWKS_CACHE_TTL_SECONDS
        if kid not in self._keys or stale:
            await self._refresh()

        if kid not in self._keys:
            raise InvalidTokenError(f"Unknown signing key: {kid!r}")
        return self._keys[kid]
