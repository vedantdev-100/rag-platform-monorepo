from jose import JWTError, jwt
from jose.exceptions import ExpiredSignatureError

from platform_auth.exceptions import InvalidTokenError, TokenExpiredError
from platform_auth.jwks import JWKSClient


async def decode_access_token(token: str, jwks_client: JWKSClient) -> dict:
    try:
        header = jwt.get_unverified_header(token)
    except JWTError as exc:
        raise InvalidTokenError("Malformed token") from exc

    jwk = await jwks_client.get_key(header.get("kid"))

    try:
        payload = jwt.decode(token, jwk, algorithms=["RS256"])
    except ExpiredSignatureError as exc:
        raise TokenExpiredError("Access token expired") from exc
    except JWTError as exc:
        raise InvalidTokenError("Invalid token signature") from exc

    if payload.get("type") != "access":
        raise InvalidTokenError("Not an access token")
    return payload
