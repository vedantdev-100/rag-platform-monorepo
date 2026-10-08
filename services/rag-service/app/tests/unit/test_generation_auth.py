from types import SimpleNamespace

import pytest
import platform_auth.dependencies as auth_dependencies

from app.rag.generation.auth import authorization_guard
from app.rag.generation.types import GenerationError


@pytest.mark.asyncio
async def test_guard_rechecks_actual_blacklist_dependency(monkeypatch):
    calls = []
    revoked = False

    async def decode(token, jwks):
        assert token == "already-verified-token"
        return {"sub": "a", "iat": 100, "role": "user", "scopes": ["rag:query"]}

    async def is_revoked(sub, iat):
        calls.append((sub, iat))
        return revoked

    async def disconnected():
        return False

    monkeypatch.setattr(auth_dependencies, "decode_access_token", decode)
    request = SimpleNamespace(
        headers={"authorization": "Bearer already-verified-token"},
        app=SimpleNamespace(
            state=SimpleNamespace(
                jwks_client=object(),
                token_blacklist=SimpleNamespace(is_token_revoked=is_revoked),
            )
        ),
        is_disconnected=disconnected,
    )
    guard = authorization_guard(request, "a")
    await guard()
    revoked = True
    with pytest.raises(GenerationError, match="authorization_lost"):
        await guard()
    assert calls == [("a", 100), ("a", 100)]


@pytest.mark.asyncio
async def test_guard_token_expiry_and_wrong_owner(monkeypatch):
    async def decode(*a):
        raise ValueError("expired token")

    async def disconnected():
        return False

    monkeypatch.setattr(auth_dependencies, "decode_access_token", decode)
    request = SimpleNamespace(
        headers={"authorization": "Bearer token"},
        app=SimpleNamespace(state=SimpleNamespace(jwks_client=object())),
        is_disconnected=disconnected,
    )
    with pytest.raises(GenerationError, match="authorization_lost"):
        await authorization_guard(request, "a")()
