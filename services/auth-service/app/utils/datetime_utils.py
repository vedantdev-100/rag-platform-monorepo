"""
Centralized datetime helpers. Before this module existed, `datetime.now(
timezone.utc)` was repeated across models/security/services — easy to
accidentally use a naive `datetime.now()` somewhere and get subtle
timezone bugs in token-expiry comparisons. Import `utcnow()` everywhere
instead.
"""
from datetime import datetime, timedelta, timezone


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def utcnow_plus(*, minutes: int = 0, days: int = 0) -> datetime:
    return utcnow() + timedelta(minutes=minutes, days=days)


def is_expired(expires_at: datetime) -> bool:
    return expires_at < utcnow()
