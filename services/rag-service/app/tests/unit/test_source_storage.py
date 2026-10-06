"""Deterministic routing and cancellation tests; no SDK or running server needed."""
import asyncio
import io
import tempfile
import threading
import unittest
from pathlib import Path

from app.rag.ingestion.storage import (
    LocalFileStorage, MinioFileStorage, RoutingFileStorage,
    StorageWriteCancelled, StorageWriteError, object_location,
)


class FakeClient:
    def __init__(self):
        self.objects = {}
        self.last_body = None
        self.fail_put = False
        self.started = threading.Event()
        self.release = threading.Event()
        self.block = False

    def put_object(self, *, Bucket, Key, Body, ContentType):
        self.started.set()
        if self.block:
            self.release.wait(timeout=5)
        # Simulate a lost PUT response after the object was actually stored.
        self.objects[(Bucket, Key)] = Body
        if self.fail_put:
            raise OSError("lost response")

    def get_object(self, *, Bucket, Key):
        self.last_body = io.BytesIO(self.objects[(Bucket, Key)])
        return {"Body": self.last_body}

    def delete_object(self, *, Bucket, Key):
        self.objects.pop((Bucket, Key), None)


class StorageTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.client = FakeClient()
        self.local = LocalFileStorage(self.directory.name)
        self.minio = MinioFileStorage(endpoint="http://minio:9000", bucket="rag-documents", access_key="test", secret_key="test", client=self.client)

    def tearDown(self):
        self.directory.cleanup()

    async def test_backend_switch_preserves_reads_and_deletes(self):
        local_uri = await self.local.save(b"legacy", "old.txt")
        routing = RoutingFileStorage(self.local, self.minio, "minio")
        object_uri = await routing.save(b"new", "report.txt")
        self.assertEqual(await routing.read(local_uri), b"legacy")
        self.assertEqual(await routing.read(object_uri), b"new")
        self.assertTrue(self.client.last_body.closed)
        # Switching new writes back to local does not break old MinIO reads.
        local_writer = RoutingFileStorage(self.local, self.minio, "local")
        self.assertEqual(await local_writer.read(object_uri), b"new")
        await routing.delete(object_uri)
        await routing.delete(object_uri)
        await routing.delete(local_uri)
        self.assertEqual(self.client.objects, {})

    async def test_same_filename_never_overwrites_source(self):
        first = await self.minio.save(b"first", "report.pdf")
        second = await self.minio.save(b"second", "report.pdf")
        self.assertNotEqual(first, second)
        self.assertEqual(await self.minio.read(first), b"first")

    async def test_put_error_keeps_uri_for_compensation(self):
        self.client.fail_put = True
        with self.assertRaises(StorageWriteError) as captured:
            await self.minio.save(b"source", "report.txt")
        self.assertEqual(await self.minio.read(captured.exception.source_uri), b"source")
        await self.minio.delete(captured.exception.source_uri)
        self.assertEqual(self.client.objects, {})

    async def test_cancellation_waits_for_put_before_cleanup(self):
        self.client.block = True
        task = asyncio.create_task(self.minio.save(b"source", "report.txt"))
        self.assertTrue(await asyncio.to_thread(self.client.started.wait, 2))
        task.cancel()
        await asyncio.sleep(0)
        self.assertFalse(task.done())
        self.client.release.set()
        with self.assertRaises(StorageWriteCancelled) as captured:
            await task
        await self.minio.delete(captured.exception.source_uri)
        self.assertEqual(self.client.objects, {})

    async def test_local_cleanup_cannot_delete_outside_upload_directory(self):
        with tempfile.TemporaryDirectory() as other:
            target = Path(other) / "keep.txt"
            target.write_text("keep")
            with self.assertRaises(ValueError):
                await self.local.delete(str(target))
            self.assertTrue(target.exists())

    async def test_object_uri_checks_bucket_and_prefix(self):
        for uri in ("s3://other/raw/test.txt", "s3://rag-documents/elsewhere/test.txt",
                    "s3://rag-documents/raw/../test.txt", "https://example.test/file"):
            with self.assertRaises(ValueError):
                await self.minio.delete(uri)
        self.assertEqual(object_location("s3://rag-documents/raw/test.txt"),
                         ("rag-documents", "raw/test.txt"))


if __name__ == "__main__":
    unittest.main()
