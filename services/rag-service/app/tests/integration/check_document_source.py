"""Read an uploaded document's raw source and compare its persisted provenance."""
import argparse
import asyncio
import hashlib
import uuid

from app.db.session import AsyncSessionLocal
from app.rag.ingestion.storage import object_location
from app.rag.ingestion.storage_factory import build_file_storage
from rag_persistence.models.document import Document


async def main(document_id):
    async with AsyncSessionLocal() as session:
        document = await session.get(Document, document_id)
        assert document is not None, "Document not found"
        uri, checksum, size = document.source_uri, document.checksum, document.file_size_bytes
        bucket, key = document.object_bucket, document.object_key
        assert uri, "Document has no source URI"
    actual = await build_file_storage().read(uri)
    assert checksum, "Legacy source has no stored checksum; this check is for Step 7 uploads"
    assert hashlib.sha256(actual).hexdigest() == checksum, "Source checksum mismatch"
    assert len(actual) == size, "Source size mismatch"
    location = object_location(uri)
    if location:
        assert location == (bucket, key), "Object location metadata differs from source URI"
    print(f"Document source, SHA-256, file size and object metadata: OK ({'minio' if location else 'local'})")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("document_id", type=uuid.UUID)
    asyncio.run(main(parser.parse_args().document_id))
