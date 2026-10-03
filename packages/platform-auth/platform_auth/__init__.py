"""
Everything a consuming service needs to do, in main.py:

    from platform_auth import setup_auth
    setup_auth(app)
"""
from fastapi import FastAPI

from platform_auth.blacklist import TokenBlacklist
from platform_auth.config import PlatformAuthSettings
from platform_auth.dependencies import require_role, require_scopes
from platform_auth.exceptions import register_auth_exception_handlers
from platform_auth.jwks import JWKSClient
from platform_auth.middleware import add_request_id
from platform_auth.models import AuthenticatedUser

__all__ = ["setup_auth", "require_scopes", "require_role", "AuthenticatedUser"]


def setup_auth(app: FastAPI, settings: PlatformAuthSettings | None = None) -> None:
    settings = settings or PlatformAuthSettings()
    app.state.jwks_client = JWKSClient(settings)
    app.state.token_blacklist = TokenBlacklist(settings)
    app.middleware("http")(add_request_id)
    register_auth_exception_handlers(app)
