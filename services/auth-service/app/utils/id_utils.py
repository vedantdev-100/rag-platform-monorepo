"""
ID generation helpers. Centralized so the ID *strategy* (UUID4 today,
possibly ULID/KSUID later for sortable primary keys) is a one-file change,
not a find-and-replace across every model.
"""
import uuid


def generate_uuid() -> uuid.UUID:
    return uuid.uuid4()
