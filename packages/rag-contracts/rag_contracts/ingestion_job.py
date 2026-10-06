"""Versioned, small Redis envelope: source bytes always remain in storage."""
from dataclasses import dataclass
import json
import uuid


@dataclass(frozen=True)
class IngestionJob:
    job_id: uuid.UUID
    document_id: uuid.UUID
    owner_id: uuid.UUID
    generation: int
    processing_version: str

    def __post_init__(self):
        if not all(isinstance(value, uuid.UUID) for value in (self.job_id, self.document_id, self.owner_id)):
            raise ValueError("Job identifiers must be UUIDs")
        if type(self.generation) is not int or self.generation < 1:
            raise ValueError("Invalid job generation")
        if not isinstance(self.processing_version, str) or not 1 <= len(self.processing_version) <= 128:
            raise ValueError("Invalid processing version")

    def as_dict(self):
        return {"v": 1, "job_id": str(self.job_id), "document_id": str(self.document_id),
                "owner_id": str(self.owner_id), "generation": self.generation,
                "processing_version": self.processing_version}

    def to_json(self):
        return json.dumps(self.as_dict(), separators=(",", ":"), sort_keys=True)

    @classmethod
    def from_json(cls, data):
        if not isinstance(data, (str, bytes)) or len(data) > 4096:
            raise ValueError("Invalid job envelope size/type")
        value = json.loads(data)
        if not isinstance(value, dict) or set(value) != {
            "v", "job_id", "document_id", "owner_id", "generation", "processing_version",
        } or type(value["v"]) is not int or value["v"] != 1:
            raise ValueError("Unsupported job envelope")
        if not all(isinstance(value[name], str) for name in ("job_id", "document_id", "owner_id")):
            raise ValueError("Invalid job identifier types")
        return cls(uuid.UUID(value["job_id"]), uuid.UUID(value["document_id"]),
                   uuid.UUID(value["owner_id"]), value["generation"], value["processing_version"])
