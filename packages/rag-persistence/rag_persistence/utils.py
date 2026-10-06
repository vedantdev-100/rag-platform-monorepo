"""Model default factories; independent of application settings/utilities."""
import uuid
from datetime import datetime, timezone


def generate_uuid() -> uuid.UUID:
    return uuid.uuid4()


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
