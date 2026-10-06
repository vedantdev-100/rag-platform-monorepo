"""One-shot private bucket initialization; never changes existing bucket policy."""
import os

from botocore.exceptions import ClientError

from app.rag.ingestion.storage import MinioFileStorage


def main() -> None:
    storage = MinioFileStorage(
        endpoint=os.environ["MINIO_ENDPOINT_URL"], bucket=os.environ["MINIO_BUCKET"],
        access_key=os.environ["MINIO_ACCESS_KEY"], secret_key=os.environ["MINIO_SECRET_KEY"],
        region=os.environ.get("MINIO_REGION", "us-east-1"),
    )
    try:
        storage.client.head_bucket(Bucket=storage.bucket)
    except ClientError as exc:
        if exc.response["Error"]["Code"] not in {"404", "NoSuchBucket", "NotFound"}:
            raise
        arguments = {"Bucket": storage.bucket}
        region = os.environ.get("MINIO_REGION", "us-east-1")
        if region != "us-east-1":
            arguments["CreateBucketConfiguration"] = {"LocationConstraint": region}
        try:
            storage.client.create_bucket(**arguments)
        except ClientError as create_exc:
            if create_exc.response["Error"]["Code"] != "BucketAlreadyOwnedByYou":
                raise
    print("MinIO bucket ready (private by default; existing policies unchanged).")


if __name__ == "__main__":
    main()
