"""
Password hashing + JWT issuance/verification.

Decisions:
- bcrypt for password hashing (industry standard, adaptive cost factor).
- RS256 for JWT (asymmetric) so downstream services (RAG service, agent
  orchestrator, evaluation service) can verify tokens with only the public
  key — they never need the ability to mint tokens.
- Access tokens are stateless and short-lived (15 min default).
- Refresh tokens are opaque random strings whose HASH is stored server-side
  (in `refresh_tokens` table / Redis), so a stolen DB dump does not leak
  usable refresh tokens, and tokens can be revoked server-side (unlike pure
  stateless JWTs, which cannot be invalidated before expiry).
"""
import secrets
from typing import Any, Optional

from jose import jwt
from passlib.context import CryptContext

from app.core.config import get_settings
from app.utils import generate_uuid, utcnow, utcnow_plus

settings = get_settings()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__rounds=settings.BCRYPT_ROUNDS)


# ---------- Password hashing ----------

def hash_password(plain_password: str) -> str:
    return pwd_context.hash(plain_password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


# ---------- Access token (JWT, RS256, stateless) ----------

def create_access_token(
    subject: str,
    role: str,
    scopes: list[str],
    expires_in_minutes: Optional[int] = None,
) -> str:
    expire = utcnow_plus(minutes=expires_in_minutes or settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload: dict[str, Any] = {
        "sub": subject,
        "role": role,
        "scopes": scopes,
        "type": "access",
        "jti": str(generate_uuid()),  # unique per token: guarantees distinct
        # tokens even for two issuances in the same second (RS256 signing is
        # deterministic for an identical payload), and gives every token a
        # stable ID for future per-token audit logging/revocation.
        "exp": expire,
        "iat": utcnow(),
    }
    return jwt.encode(payload, settings.jwt_private_key, algorithm=settings.JWT_ALGORITHM, headers={"kid": settings.JWT_KEY_ID},)


def decode_access_token(token: str) -> dict:
    """Raises jose.JWTError on invalid/expired token — caller must handle."""
    return jwt.decode(token, settings.jwt_public_key, algorithms=[settings.JWT_ALGORITHM])


# ---------- Refresh token (opaque random string, hashed at rest) ----------

def generate_refresh_token() -> str:
    """Cryptographically secure random token — NOT a JWT. Opaque by design."""
    return secrets.token_urlsafe(64)


def hash_refresh_token(token: str) -> str:
    """We store only the hash, same principle as password storage."""
    return pwd_context.hash(token)


def verify_refresh_token(plain_token: str, hashed_token: str) -> bool:
    return pwd_context.verify(plain_token, hashed_token)


def refresh_token_expiry():
    return utcnow_plus(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
