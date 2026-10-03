"""
JWKS endpoint what makes key rotation dynamic. Every other service's
platform_auth.JWKSClient fetches and caches this; add a new key here
(bump JWT_KEY_ID + keep the old key available until its longest-lived
token expires) and no consuming service needs to redeploy.
"""
from cryptography.hazmat.primitives import serialization
from fastapi import APIRouter
from jose.utils import base64url_encode

from app.core.config import get_settings

router = APIRouter(tags=["well-known"])
settings = get_settings()


@router.get("/.well-known/jwks.json")
async def jwks():
    public_key = serialization.load_pem_public_key(settings.jwt_public_key.encode())
    numbers = public_key.public_numbers()
    n = numbers.n.to_bytes((numbers.n.bit_length() + 7) // 8, "big")
    e = numbers.e.to_bytes((numbers.e.bit_length() + 7) // 8, "big")
    return {
        "keys": [{
            "kty": "RSA", "use": "sig", "alg": settings.JWT_ALGORITHM, "kid": settings.JWT_KEY_ID,
            "n": base64url_encode(n).decode(), "e": base64url_encode(e).decode(),
        }]
    }
