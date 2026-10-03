"""
Local-disk FileStorage implementation. Raw uploaded files are NEVER stored
as bytes in Postgres — only this URI goes in Document.source_uri. Blobs in
a relational DB row bloat table/index size and slow down every unrelated
query on that table; object storage (or plain disk, for now) is the
correct place for them regardless of scale.

Swapping to S3/GCS later means writing one new class implementing
FileStorage (e.g. S3FileStorage using boto3/aioboto3) — nothing in
IngestionService or the API layer changes, since they depend on the
FileStorage interface, not this implementation.
"""
import uuid
from pathlib import Path

import aiofiles

from app.rag.ingestion.base import FileStorage


class LocalFileStorage(FileStorage):
    def __init__(self, base_dir: str):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    async def save(self, content: bytes, filename: str) -> str:
        # Prefix with a UUID so two uploads named "report.pdf" never collide.
        safe_name = f"{uuid.uuid4()}_{Path(filename).name}"
        path = self.base_dir / safe_name
        async with aiofiles.open(path, "wb") as f:
            await f.write(content)
        return str(path)

    async def read(self, uri: str) -> bytes:
        async with aiofiles.open(uri, "rb") as f:
            return await f.read()

    async def delete(self, uri: str) -> None:
        Path(uri).unlink(missing_ok=True)
