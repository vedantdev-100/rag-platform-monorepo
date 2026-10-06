"""Add Step 7 settings without replacing the user's full config.py."""
import ast
from pathlib import Path

path = Path(__file__).resolve().parents[1] / "services/rag-service/app/core/config.py"
source = path.read_text(encoding="utf-8")
if 'def _validate_minio_storage(' in source:
    print("Step 7 settings already present; no changes made.")
    raise SystemExit(0)
needle = '    STORAGE_BACKEND: Literal["local"] = "local"'
if source.count(needle) != 1:
    raise SystemExit("Expected local storage setting not found exactly once; apply the snippet from the guide manually.")
replacement = '''    STORAGE_BACKEND: Literal["local", "minio"] = "local"
    MINIO_ENDPOINT_URL: str = "http://minio:9000"
    MINIO_BUCKET: str = "rag-documents"
    MINIO_ACCESS_KEY: str = ""
    MINIO_SECRET_KEY: SecretStr = SecretStr("")
    MINIO_REGION: str = "us-east-1"

    @model_validator(mode="after")
    def _validate_minio_storage(self) -> "Settings":
        import re
        from urllib.parse import urlsplit
        configured = bool(self.MINIO_ACCESS_KEY or self.MINIO_SECRET_KEY.get_secret_value())
        if self.STORAGE_BACKEND == "minio" or configured:
            if not self.MINIO_ACCESS_KEY or not self.MINIO_SECRET_KEY.get_secret_value():
                raise ValueError("MinIO requires both MINIO_ACCESS_KEY and MINIO_SECRET_KEY")
            endpoint = urlsplit(self.MINIO_ENDPOINT_URL)
            if (endpoint.scheme not in {"http", "https"} or not endpoint.netloc
                    or endpoint.path not in {"", "/"} or endpoint.query or endpoint.fragment
                    or endpoint.username or endpoint.password):
                raise ValueError("MINIO_ENDPOINT_URL must be an HTTP(S) server URL without credentials")
            if not re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]", self.MINIO_BUCKET):
                raise ValueError("MINIO_BUCKET must be a 3-63 character lowercase bucket name")
        return self
'''
updated = source.replace(needle, replacement)
ast.parse(updated)
path.write_text(updated, encoding="utf-8")
print("Added MinIO settings and validation; existing settings preserved.")
