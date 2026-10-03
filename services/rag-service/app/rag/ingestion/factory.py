"""
Builds ingestion backends from Settings rather than hardcoding a choice
anywhere that uses them — changing RAG_CHUNKER_BACKEND from "docling" to
"simple" in .env, for example, requires no code change. This is the single
place that maps a config string to a concrete class; IngestionService and
the API layer only ever depend on the interfaces in base.py.

Backends that load models raise ModelNotFoundError (HTTP 503, with the fix
in the message) when the model isn't downloaded yet. lru_cache never caches
an exception, so once `download_models` has run the next request just works
— no restart needed.
"""
from functools import lru_cache

from app.core.config import get_settings
from app.rag.ingestion.base import Chunker, DocumentParser, EmbeddingGenerator, FileStorage
from app.rag.ingestion.chunking.docling_chunker import DoclingHybridChunker
from app.rag.ingestion.chunking.simple_chunker import SimpleChunker
from app.rag.ingestion.chunking.tokenizers import build_tokenizer
from app.rag.ingestion.embeddings.stub_embedder import StubEmbeddingGenerator
from app.rag.ingestion.model_paths import require_local_model
from app.rag.ingestion.parsers.docling_parser import DoclingParser
from app.rag.ingestion.storage import LocalFileStorage

settings = get_settings()


def get_file_storage() -> FileStorage:
    if settings.STORAGE_BACKEND == "local":
        return LocalFileStorage(settings.LOCAL_STORAGE_DIR)
    raise ValueError(f"Unknown STORAGE_BACKEND: {settings.STORAGE_BACKEND!r}")


@lru_cache
def get_document_parser() -> DocumentParser:
    if settings.RAG_PARSER_BACKEND == "docling":
        return DoclingParser(settings)
    raise ValueError(f"Unknown RAG_PARSER_BACKEND: {settings.RAG_PARSER_BACKEND!r}")


@lru_cache
def get_chunker() -> Chunker:
    if settings.RAG_CHUNKER_BACKEND == "docling":
        return DoclingHybridChunker(
            tokenizer=build_tokenizer(settings), merge_peers=settings.RAG_CHUNKER_MERGE_PEERS
        )
    if settings.RAG_CHUNKER_BACKEND == "simple":
        return SimpleChunker()
    raise ValueError(f"Unknown RAG_CHUNKER_BACKEND: {settings.RAG_CHUNKER_BACKEND!r}")


@lru_cache
def get_embedding_generator() -> EmbeddingGenerator:
    if settings.RAG_EMBEDDING_BACKEND == "stub":
        return StubEmbeddingGenerator(dimensions=settings.EMBEDDING_DIMENSIONS)
    if settings.RAG_EMBEDDING_BACKEND == "sentence_transformers":
        from app.rag.ingestion.embeddings.sentence_transformers_embedder import SentenceTransformersEmbedder

        return SentenceTransformersEmbedder(
            model_path=require_local_model(settings.RAG_EMBEDDING_MODEL, settings),
            dimensions=settings.EMBEDDING_DIMENSIONS,
            batch_size=settings.RAG_EMBEDDING_BATCH_SIZE,
            device=settings.RAG_EMBEDDING_DEVICE,
        )
    raise ValueError(f"Unknown RAG_EMBEDDING_BACKEND: {settings.RAG_EMBEDDING_BACKEND!r}")
