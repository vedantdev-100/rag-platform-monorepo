import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    source_type: str
    status: str
    doc_metadata: dict
    created_at: datetime


class DocumentListOut(BaseModel):
    documents: list[DocumentOut]
    total: int
