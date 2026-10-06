"""Run at monorepo root. Add remote parser settings, preserving existing values."""
import ast
from pathlib import Path

path = Path('services/rag-service/app/core/config.py')
text = path.read_text(encoding='utf-8')
marker = '    # Step 10B: version-pinned remote parser contract.\n'
if marker in text:
    ast.parse(text)
    print('Step 10B settings already present; no changes')
    raise SystemExit(0)
old = '    RAG_PARSER_BACKEND: Literal["docling"] = "docling"'
if text.count(old) != 1:
    raise SystemExit('Settings parser declaration differs. Send current config.py before applying.')
addition = '''    RAG_PARSER_BACKEND: Literal["docling", "docling_serve"] = "docling"
    # Step 10B: version-pinned remote parser contract.
    DOCLING_SERVE_URL: str = "http://docling-serve:5001"
    DOCLING_SERVE_API_KEY: SecretStr = SecretStr("")
    DOCLING_SERVE_EXPECTED_VERSION: str = "1.21.0"
    DOCLING_SERVE_EXPECTED_DOCLING_VERSION: str = "2.96.1"
    DOCLING_SERVE_EXPECTED_CORE_VERSION: str = "2.78.0"
    DOCLING_SERVE_DOCUMENT_TIMEOUT_SECONDS: int = 600
    DOCLING_SERVE_HTTP_TIMEOUT_SECONDS: int = 630
    DOCLING_SERVE_MAX_RESPONSE_MB: int = 50

    @model_validator(mode="after")
    def _validate_docling_serve(self) -> "Settings":
        if self.RAG_PARSER_BACKEND != "docling_serve":
            return self
        from urllib.parse import urlsplit
        url = urlsplit(self.DOCLING_SERVE_URL)
        if (url.scheme not in {"http", "https"} or not url.netloc or url.path not in {"", "/"}
                or url.username or url.password or url.query or url.fragment):
            raise ValueError("DOCLING_SERVE_URL must be a server URL without credentials or paths")
        if not (30 <= self.DOCLING_SERVE_DOCUMENT_TIMEOUT_SECONDS
                < self.DOCLING_SERVE_HTTP_TIMEOUT_SECONDS < self.INGESTION_JOB_TIMEOUT_SECONDS - 30):
            raise ValueError("Docling document < HTTP < job timeout minus 30 seconds required")
        if not (1 <= self.DOCLING_SERVE_MAX_RESPONSE_MB <= 100) or self.RAG_PARSER_MAX_CONCURRENCY < 1:
            raise ValueError("Invalid remote parser response/concurrency limits")
        if (self.RAG_PICTURE_DESCRIPTION_ENABLED and self.RAG_PICTURE_MIN_AREA != 0.05):
            raise ValueError("Remote picture threshold other than 0.05 needs a server preset before switching")
        return self
'''
updated = text.replace(old, addition.rstrip(), 1)
ast.parse(updated)
backup = path.with_suffix('.py.step10b.bak')
if not backup.exists():
    backup.write_text(text, encoding='utf-8')
path.write_text(updated, encoding='utf-8')
print('Remote parser settings added; existing defaults/settings retained')
