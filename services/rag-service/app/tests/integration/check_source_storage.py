"""Round-trip a disposable source through the actual configured backend."""
import asyncio
import hashlib

from app.rag.ingestion.storage_factory import build_file_storage
from app.rag.ingestion.storage import object_location


async def main() -> None:
    storage = build_file_storage()
    content = b"Step 7 source storage integration check.\n"
    uri = await storage.save(content, "step07-storage-check.txt")
    try:
        actual = await storage.read(uri)
        assert hashlib.sha256(actual).digest() == hashlib.sha256(content).digest(), "Source bytes changed"
        print(f"Source write/read/checksum: OK ({'minio' if object_location(uri) else 'local'})")
    finally:
        await storage.delete(uri)
    await storage.delete(uri)
    print("Source deletion, including repeated deletion: OK")


if __name__ == "__main__":
    asyncio.run(main())
