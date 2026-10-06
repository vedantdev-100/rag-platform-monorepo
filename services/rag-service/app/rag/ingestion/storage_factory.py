"""Storage construction is separate from factories that import ML libraries."""
from functools import lru_cache

from app.core.config import get_settings
from app.rag.ingestion.base import FileStorage
from app.rag.ingestion.storage import LocalFileStorage, MinioFileStorage, RoutingFileStorage


@lru_cache
def build_file_storage() -> FileStorage:
    settings = get_settings()
    local = LocalFileStorage(settings.LOCAL_STORAGE_DIR)
    minio = None
    if settings.MINIO_ACCESS_KEY and settings.MINIO_SECRET_KEY.get_secret_value():
        minio = MinioFileStorage(
            endpoint=settings.MINIO_ENDPOINT_URL, bucket=settings.MINIO_BUCKET,
            access_key=settings.MINIO_ACCESS_KEY,
            secret_key=settings.MINIO_SECRET_KEY.get_secret_value(), region=settings.MINIO_REGION,
        )
    if settings.STORAGE_BACKEND == "minio" and minio is None:
        raise ValueError("MinIO credentials are required")
    return RoutingFileStorage(local, minio, settings.STORAGE_BACKEND)
