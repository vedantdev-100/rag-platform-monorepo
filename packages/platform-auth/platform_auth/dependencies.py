from fastapi import Depends, Request
from fastapi.security import OAuth2PasswordBearer

from platform_auth.blacklist import TokenBlacklist
from platform_auth.exceptions import InsufficientPermissionsError, InvalidTokenError
from platform_auth.models import AuthenticatedUser
from platform_auth.tokens import decode_access_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)


def get_current_user_dependency():
    """
    Factory, not a bare function  setup_auth() calls this once at
    startup with the service's own JWKSClient/TokenBlacklist instances
    (stashed on app.state) and gets back a ready-to-use dependency.
    """
    async def _dependency(request: Request, token: str | None = Depends(oauth2_scheme)) -> AuthenticatedUser:
        if token is None:
            raise InvalidTokenError("Missing Authorization header")
        payload = await decode_access_token(token, request.app.state.jwks_client)

        blacklist: TokenBlacklist = request.app.state.token_blacklist
        # if await blacklist.is_revoked(payload.get("jti", "")):
        #     raise InvalidTokenError("Token has been revoked")
        if await blacklist.is_token_revoked(payload["sub"], payload["iat"]):
            raise InvalidTokenError("Token has been revoked")
        
        return AuthenticatedUser(id=payload["sub"], role=payload["role"], scopes=payload.get("scopes", []))

    return _dependency


def require_scopes(*required_scopes: str):
    def _factory(current_user: AuthenticatedUser = Depends(get_current_user_dependency())) -> AuthenticatedUser:
        if not all(current_user.has_scope(s) for s in required_scopes):
            raise InsufficientPermissionsError(f"Missing required scope(s): {', '.join(required_scopes)}")
        return current_user
    return _factory


def require_role(*allowed_roles: str):
    def _factory(current_user: AuthenticatedUser = Depends(get_current_user_dependency())) -> AuthenticatedUser:
        if current_user.role not in allowed_roles:
            raise InsufficientPermissionsError("You do not have permission to perform this action")
        return current_user
    return _factory
