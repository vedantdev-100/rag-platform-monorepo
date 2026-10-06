"""Pure identity/configuration/vector checks used by API and worker."""
import hashlib
import json
import math


def processing_version(settings):
    names = ["RAG_PARSER_BACKEND", "RAG_OCR_ENABLED", "RAG_TABLE_STRUCTURE_ENABLED",
             "RAG_PICTURE_DESCRIPTION_ENABLED", "RAG_PICTURE_DESCRIPTION_BACKEND",
             "RAG_PICTURE_DESCRIPTION_MODEL", "RAG_PICTURE_DESCRIPTION_API_MODEL",
             "RAG_PICTURE_DESCRIPTION_PROMPT", "RAG_PICTURE_MIN_AREA",
             "RAG_CHUNKER_BACKEND", "RAG_CHUNKER_TOKENIZER", "RAG_CHUNKER_TOKENIZER_MODEL",
             "RAG_CHUNKER_MAX_TOKENS", "RAG_CHUNKER_MERGE_PEERS",
             "RAG_EMBEDDING_BACKEND", "RAG_EMBEDDING_MODEL", "EMBEDDING_DIMENSIONS"]
    data = {name: getattr(settings, name) for name in names}
    if settings.RAG_PARSER_BACKEND == "docling_serve":
        for name in ("DOCLING_SERVE_EXPECTED_VERSION", "DOCLING_SERVE_EXPECTED_DOCLING_VERSION",
                     "DOCLING_SERVE_EXPECTED_CORE_VERSION", "DOCLING_SERVE_DOCUMENT_TIMEOUT_SECONDS"):
            data[name] = getattr(settings, name)
        # Explicit adapter revision: alter when conversion semantics change.
        data["parser_adapter"] = "docling-serve-v1-json-1"
        data["picture_api_url"] = settings.RAG_PICTURE_DESCRIPTION_API_URL
    return "ingestion-v1:" + hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


def matches(document, job):
    return document is not None and (
        document.id, document.owner_id, document.job_id, document.generation, document.processing_version
    ) == (job.document_id, job.owner_id, job.job_id, job.generation, job.processing_version)


def can_complete(document, job, token, now):
    return (matches(document, job) and document.status == "processing"
            and document.processing_token == token and document.processing_lease_until is not None
            and document.processing_lease_until > now)


def validate_vectors(vectors, count, provider_dimension, expected_dimension=768):
    if provider_dimension != expected_dimension or len(vectors) != count:
        raise ValueError("Embedding dimension/count mismatch")
    for vector in vectors:
        if len(vector) != expected_dimension:
            raise ValueError("Embedding length mismatch")
        try:
            valid = all(not isinstance(value, bool) and math.isfinite(value) for value in vector)
        except (ValueError, TypeError, OverflowError):
            valid = False
        if not valid:
            raise ValueError("Embedding contains invalid/non-finite values")
