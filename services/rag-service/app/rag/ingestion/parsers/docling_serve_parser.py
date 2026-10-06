"""Docling Serve v1 adapter. No conversion/model imports or DB transactions."""
import asyncio
import copy
import json
from pathlib import Path

import httpx
from docling_core.types.doc.document import BaseMeta, DoclingDocument
from pydantic import ValidationError

from app.exceptions import IngestionError
from app.rag.ingestion.base import DocumentParser, ParsedDocument
from app.rag.ingestion.parsers.docling_document import flatten_docling_document
from app.rag.ingestion.source_types import SUPPORTED_SOURCE_TYPES


class DoclingServeUnavailable(RuntimeError):
    """Retryable infrastructure failure; the existing queue bounds attempts."""


class DoclingServeConfigurationError(RuntimeError):
    """Config/API mismatch. Fail closed, with bounded retries and retained source."""


class DoclingServeVersionMismatch(DoclingServeConfigurationError):
    pass


class DoclingServeSchemaMismatch(DoclingServeConfigurationError):
    pass


class DoclingServeConversionFailed(RuntimeError):
    """May be a transient model failure; bounded retries, no partial indexing."""


class DoclingServePartialConversion(IngestionError):
    pass


def form_options(settings):
    # Names and representations checked against the uploaded 1.21.0 OpenAPI.
    result = {
        "target_type": "inbody", "to_formats": "json", "image_export_mode": "placeholder",
        "do_ocr": str(settings.RAG_OCR_ENABLED).lower(),
        "do_table_structure": str(settings.RAG_TABLE_STRUCTURE_ENABLED).lower(),
        "do_picture_description": str(settings.RAG_PICTURE_DESCRIPTION_ENABLED).lower(),
        "document_timeout": str(settings.DOCLING_SERVE_DOCUMENT_TIMEOUT_SECONDS),
        "abort_on_error": "true",
    }
    if settings.RAG_PICTURE_DESCRIPTION_ENABLED:
        # These version-pinned legacy fields are advertised by this deployment.
        # Their schema does not expose picture_area_threshold; reject custom
        # thresholds instead of silently changing the existing parser behavior.
        if settings.RAG_PICTURE_MIN_AREA != 0.05:
            raise DoclingServeConfigurationError("Picture threshold other than 0.05 needs a server preset")
        options = {"prompt": settings.RAG_PICTURE_DESCRIPTION_PROMPT}
        if settings.RAG_PICTURE_DESCRIPTION_BACKEND == "api":
            headers = {}
            key = settings.RAG_PICTURE_DESCRIPTION_API_KEY.get_secret_value()
            if key:
                headers["Authorization"] = f"Bearer {key}"
            options.update(url=settings.RAG_PICTURE_DESCRIPTION_API_URL, headers=headers,
                           params={"model": settings.RAG_PICTURE_DESCRIPTION_API_MODEL},
                           timeout=settings.RAG_PICTURE_DESCRIPTION_TIMEOUT, concurrency=1)
            result["picture_description_api"] = json.dumps(options)
        else:
            options["repo_id"] = settings.RAG_PICTURE_DESCRIPTION_MODEL
            result["picture_description_local"] = json.dumps(options)
    return result


def verify_schema(schema, requested):
    try:
        endpoint = schema["paths"]["/v1/convert/file"]["post"]
        ref = endpoint["requestBody"]["content"]["multipart/form-data"]["schema"]["$ref"]
        properties = schema["components"]["schemas"][ref.rsplit("/", 1)[-1]]["properties"]
    except (KeyError, TypeError, AttributeError) as exc:
        raise DoclingServeSchemaMismatch("Missing multipart v1 conversion schema") from exc
    if not {"files", *requested}.issubset(properties):
        raise DoclingServeSchemaMismatch("Server does not advertise the required conversion options")


def project_core_metadata(raw):
    """Known 2.78 -> 2.74 metadata bridge; never discard nonempty fields.

    The shared 1.10.0 document schema gained language/entities meta fields.
    Older core rejects unnamespaced custom meta. Preserve these new fields
    as namespaced custom metadata when the installed SDK lacks them.
    Unknown structural changes still fail DoclingDocument validation.
    """
    value = copy.deepcopy(raw)
    projected = set()
    def visit(node):
        if isinstance(node, dict):
            meta = node.get("meta")
            if isinstance(meta, dict):
                for field in ("language", "entities"):
                    if field in meta and field not in BaseMeta.model_fields:
                        original = meta.pop(field)
                        if original is not None:
                            target = "docling_serve__" + field
                            if target in meta:
                                raise DoclingServeSchemaMismatch("Conflicting projected metadata")
                            meta[target] = original
                        projected.add(field)
            for child in node.values():
                visit(child)
        elif isinstance(node, list):
            for child in node:
                visit(child)
    visit(value)
    return value, sorted(projected)


def decode_document(payload, settings):
    if not isinstance(payload, dict):
        raise DoclingServeSchemaMismatch("Expected conversion object")
    status = payload.get("status")
    if status == "partial_success":
        raise DoclingServePartialConversion("Partial conversion is not indexed")
    if status == "failure":
        raise DoclingServeConversionFailed("Conversion failed; source retained")
    if status != "success" or payload.get("errors"):
        raise DoclingServeSchemaMismatch("Conversion is not a clean success")
    document = payload.get("document")
    raw = document.get("json_content") if isinstance(document, dict) else None
    if not isinstance(raw, dict):
        raise DoclingServeSchemaMismatch("Structured json_content is missing")
    try:
        compatible, projected = project_core_metadata(raw)
        native = DoclingDocument.model_validate(compatible)
        elements, stats = flatten_docling_document(native)
    except (ValidationError, ValueError, TypeError, KeyError, AttributeError) as exc:
        raise DoclingServeSchemaMismatch("Remote document cannot be decoded by the installed docling-core") from exc
    stats["parser_metadata_projection"] = projected
    stats.update(parser_provider="docling_serve", parser_version=settings.DOCLING_SERVE_EXPECTED_VERSION,
                 parser_docling_version=settings.DOCLING_SERVE_EXPECTED_DOCLING_VERSION,
                 parser_core_version=settings.DOCLING_SERVE_EXPECTED_CORE_VERSION)
    return ParsedDocument(elements=elements, metadata=stats, native=native)


class DoclingServeParser(DocumentParser):
    supported_source_types = SUPPORTED_SOURCE_TYPES

    def __init__(self, settings, *, transport=None):
        self.settings = settings
        self._transport = transport  # MockTransport only in tests.
        self._slots = asyncio.Semaphore(settings.RAG_PARSER_MAX_CONCURRENCY)

    async def _json(self, client, method, path, *, limit=None, **kwargs):
        limit = limit or self.settings.DOCLING_SERVE_MAX_RESPONSE_MB * 1024 * 1024
        try:
            async with client.stream(method, path, **kwargs) as response:
                code = response.status_code
                if code in (408, 429) or code >= 500:
                    raise DoclingServeUnavailable(f"Docling HTTP {code}")
                if code == 413:
                    raise IngestionError("Document exceeds the Docling server size limit")
                if code != 200:
                    # 422 is request configuration validation, not proof that
                    # the uploaded file itself is invalid. Never log bodies.
                    raise DoclingServeConfigurationError(f"Unexpected Docling HTTP {code}")
                data = bytearray()
                async for part in response.aiter_bytes():
                    if len(data) + len(part) > limit:
                        raise DoclingServeSchemaMismatch("Docling JSON exceeds the configured response limit")
                    data.extend(part)
                try:
                    return json.loads(data)
                except (ValueError, UnicodeDecodeError) as exc:
                    raise DoclingServeSchemaMismatch("Docling response is not JSON") from exc
        except httpx.RequestError as exc:
            raise DoclingServeUnavailable("Docling transport error") from exc

    async def parse(self, content, filename):
        suffix = Path(filename).suffix.lower()
        suffix = {".txt": ".md", ".htm": ".html"}.get(suffix, suffix)
        if suffix.removeprefix(".") not in self.supported_source_types:
            raise IngestionError("Unsupported document extension")
        if not content or len(content) > self.settings.RAG_MAX_UPLOAD_MB * 1024 * 1024:
            raise IngestionError("Document is empty or exceeds the upload limit")
        options = form_options(self.settings)
        headers = {}
        key = self.settings.DOCLING_SERVE_API_KEY.get_secret_value()
        if key:
            headers["X-Api-Key"] = key
        timeout = httpx.Timeout(self.settings.DOCLING_SERVE_HTTP_TIMEOUT_SECONDS,
                                connect=10, write=30, pool=10)
        async with self._slots:
            async with httpx.AsyncClient(base_url=self.settings.DOCLING_SERVE_URL.rstrip('/') + '/',
                    headers=headers, timeout=timeout, transport=self._transport,
                    follow_redirects=False, trust_env=False,
                    limits=httpx.Limits(max_connections=1, max_keepalive_connections=1)) as client:
                versions = await self._json(client, "GET", "version", limit=65536)
                expected = {"docling-serve": self.settings.DOCLING_SERVE_EXPECTED_VERSION,
                            "docling": self.settings.DOCLING_SERVE_EXPECTED_DOCLING_VERSION,
                            "docling-core": self.settings.DOCLING_SERVE_EXPECTED_CORE_VERSION}
                if not isinstance(versions, dict) or any(versions.get(k) != v for k, v in expected.items()):
                    raise DoclingServeVersionMismatch("Server versions differ from the configured conversion contract")
                schema = await self._json(client, "GET", "openapi.json", limit=4 * 1024 * 1024)
                verify_schema(schema, options)
                # No paths or filenames from storage are shared with the server.
                # Bytes already fetched from MinIO are posted as one multipart file.
                payload = await self._json(client, "POST", "v1/convert/file", data=options,
                    files={"files": ("document" + suffix, content, "application/octet-stream")})
        return await asyncio.to_thread(decode_document, payload, self.settings)
