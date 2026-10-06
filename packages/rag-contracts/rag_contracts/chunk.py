"""Chunk payload before database persistence."""
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ChunkData:
    """Output of chunking — what ChunkRepository.bulk_create() persists,
    minus document_id/chunk_index/embedding (the pipeline fills those in)."""
    content: str
    modality: str = "text"
    metadata: dict[str, Any] = field(default_factory=dict)
