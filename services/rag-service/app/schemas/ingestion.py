"""Queue-aware response; existing document/list schema remains unchanged."""
import uuid
from datetime import datetime

from app.schemas.document import DocumentOut


class DocumentJobOut(DocumentOut):
    job_id: uuid.UUID | None = None
    generation: int
    retry_count: int
    failure_reason: str | None = None
    processed_at: datetime | None = None
