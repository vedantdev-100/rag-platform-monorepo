"""Local and S3-compatible source storage; dispatch reads by persisted URI."""
from __future__ import annotations

import asyncio
import mimetypes
import re
import uuid
from pathlib import Path, PureWindowsPath
from urllib.parse import quote, unquote, urlsplit

from app.rag.ingestion.base import FileStorage


class StorageWriteError(RuntimeError):
    def __init__(self, source_uri: str):
        super().__init__("Source storage write failed")
        self.source_uri = source_uri


class StorageWriteCancelled(asyncio.CancelledError):
    def __init__(self, source_uri: str):
        super().__init__("Source storage write cancelled")
        self.source_uri = source_uri


async def _write_at_uri(operation, uri: str) -> None:
    # Wait for a bounded SDK write on cancellation, so cleanup is not queued
    # while a background thread could still create the object afterward.
    task = asyncio.create_task(asyncio.to_thread(operation))
    try:
        await asyncio.shield(task)
    except asyncio.CancelledError:
        try:
            await task
        except Exception:
            pass
        raise StorageWriteCancelled(uri) from None
    except Exception as exc:
        raise StorageWriteError(uri) from exc


def object_location(uri: str) -> tuple[str, str] | None:
    parts = urlsplit(uri)
    if parts.scheme != "s3":
        return None
    if not parts.netloc or parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError("Invalid source object URI")
    key = unquote(parts.path.lstrip("/"))
    if not key.startswith("raw/") or ".." in key.split("/") or "\\" in key:
        raise ValueError("Invalid source object key")
    return parts.netloc, key


class LocalFileStorage(FileStorage):
    def __init__(self, base_dir: str):
        self.base_dir = Path(base_dir).resolve()
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, uri: str) -> Path:
        # A persisted URI is internal, but cleanup must not unlink arbitrary
        # paths if a legacy row contains an unexpected value.
        windows_drive = bool(PureWindowsPath(uri).drive)
        if (urlsplit(uri).scheme and not windows_drive) or (windows_drive and not Path(uri).is_absolute()):
            raise ValueError("Unsupported local source URI on this operating system")
        path = Path(uri).resolve()
        if not path.is_relative_to(self.base_dir) or path == self.base_dir:
            raise ValueError("Local source is outside the upload directory")
        return path

    def allocate(self, filename: str, document_id: uuid.UUID, owner_id: uuid.UUID) -> str:
        name = Path(filename.replace("\\", "/")).name or "upload"
        return str(self.base_dir / f"{document_id}_{name}")

    async def write(self, uri: str, content: bytes, filename: str) -> None:
        await _write_at_uri(lambda: self._path(uri).write_bytes(content), uri)

    async def save(self, content: bytes, filename: str) -> str:
        uri = self.allocate(filename, uuid.uuid4(), uuid.uuid4())
        await self.write(uri, content, filename)
        return uri

    async def read(self, uri: str) -> bytes:
        path = self._path(uri)
        return await asyncio.to_thread(path.read_bytes)

    async def delete(self, uri: str) -> None:
        path = self._path(uri)
        await asyncio.to_thread(path.unlink, missing_ok=True)


class MinioFileStorage(FileStorage):
    def __init__(self, *, endpoint: str, bucket: str, access_key: str, secret_key: str,
                 region: str = "us-east-1", client=None):
        self.bucket = bucket
        if client is None:
            import boto3
            from botocore.config import Config
            client = boto3.client(
                "s3", endpoint_url=endpoint, aws_access_key_id=access_key,
                aws_secret_access_key=secret_key, region_name=region,
                config=Config(signature_version="s3v4", connect_timeout=5, read_timeout=20,
                              retries={"mode": "standard", "total_max_attempts": 3},
                              s3={"addressing_style": "path"},
                              request_checksum_calculation="when_required",
                              response_checksum_validation="when_required"),
            )
        self.client = client

    def _location(self, uri: str) -> tuple[str, str]:
        result = object_location(uri)
        if result is None or result[0] != self.bucket:
            raise ValueError("Source URI does not belong to the configured bucket")
        return result

    def allocate(self, filename: str, document_id: uuid.UUID, owner_id: uuid.UUID) -> str:
        suffix = Path(filename.replace("\\", "/")).suffix.lower()
        if not re.fullmatch(r"\.[a-z0-9]{1,12}", suffix):
            suffix = ""
        key = f"raw/{owner_id.hex}/{document_id.hex}{suffix}"
        return f"s3://{self.bucket}/{quote(key, safe='/')}"

    async def write(self, uri: str, content: bytes, filename: str) -> None:
        bucket, key = self._location(uri)
        mime = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        await _write_at_uri(
            lambda: self.client.put_object(Bucket=bucket, Key=key, Body=content, ContentType=mime), uri,
        )

    async def save(self, content: bytes, filename: str) -> str:
        uri = self.allocate(filename, uuid.uuid4(), uuid.uuid4())
        await self.write(uri, content, filename)
        return uri

    async def read(self, uri: str) -> bytes:
        bucket, key = self._location(uri)
        def get():
            body = self.client.get_object(Bucket=bucket, Key=key)["Body"]
            try:
                return body.read()
            finally:
                body.close()
        return await asyncio.to_thread(get)

    async def delete(self, uri: str) -> None:
        bucket, key = self._location(uri)
        await asyncio.to_thread(self.client.delete_object, Bucket=bucket, Key=key)


class RoutingFileStorage(FileStorage):
    """New writes follow the setting; existing reads/deletes follow the URI."""
    def __init__(self, local: LocalFileStorage, minio: MinioFileStorage | None, backend: str):
        self.local, self.minio, self.backend = local, minio, backend

    def _reader(self, uri: str) -> FileStorage:
        if object_location(uri) is not None:
            if self.minio is None:
                raise ValueError("MinIO credentials are required for existing object sources")
            return self.minio
        return self.local

    def allocate(self, filename: str, document_id: uuid.UUID, owner_id: uuid.UUID) -> str:
        writer = self.minio if self.backend == "minio" else self.local
        if writer is None:
            raise ValueError("MinIO writer is not configured")
        return writer.allocate(filename, document_id, owner_id)

    async def write(self, uri: str, content: bytes, filename: str) -> None:
        await self._reader(uri).write(uri, content, filename)

    async def save(self, content: bytes, filename: str) -> str:
        writer = self.minio if self.backend == "minio" else self.local
        if writer is None:
            raise ValueError("MinIO writer is not configured")
        return await writer.save(content, filename)

    async def read(self, uri: str) -> bytes:
        return await self._reader(uri).read(uri)

    async def delete(self, uri: str) -> None:
        await self._reader(uri).delete(uri)
