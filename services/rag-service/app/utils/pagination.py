"""
Shared pagination schema + helper. Not used by auth yet, but every future
list endpoint (documents, ingestion jobs, eval results) will need the same
shape — defined once here instead of reinvented per endpoint.
"""
from typing import Generic, Sequence, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: Sequence[T]
    total: int
    limit: int
    offset: int

    @property
    def has_more(self) -> bool:
        return self.offset + len(self.items) < self.total


def clamp_pagination(limit: int, offset: int, *, max_limit: int = 100) -> tuple[int, int]:
    """Defensive clamp so a client can't request limit=999999 and hammer the DB."""
    return max(1, min(limit, max_limit)), max(0, offset)
