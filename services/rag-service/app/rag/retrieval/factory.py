"""
Builds retrieval backends from Settings — same philosophy as
ingestion/factory.py. Swap RAG_RETRIEVER_BACKEND or RAG_RERANKER_BACKEND in
.env with no code change anywhere that calls get_retriever()/get_reranker().
"""
from app.core.config import get_settings
from app.rag.ingestion.factory import get_embedding_generator
from app.rag.ingestion.model_paths import require_local_model
from app.rag.retrieval.base import Reranker, Retriever
from app.rag.retrieval.hybrid_retriever import HybridRetriever
from app.rag.retrieval.keyword_retriever import KeywordRetriever
from app.rag.retrieval.vector_retriever import VectorRetriever
from app.repositories.chunk_repository import ChunkRepository

settings = get_settings()


def get_retriever(chunk_repo: ChunkRepository) -> Retriever:
    if settings.RAG_RETRIEVER_BACKEND == "vector":
        return VectorRetriever(chunk_repo, get_embedding_generator())
    if settings.RAG_RETRIEVER_BACKEND == "keyword":
        return KeywordRetriever(chunk_repo)
    if settings.RAG_RETRIEVER_BACKEND == "hybrid":
        return HybridRetriever(
            VectorRetriever(chunk_repo, get_embedding_generator()),
            KeywordRetriever(chunk_repo),
            rrf_k=settings.RAG_RRF_K,
        )
    raise ValueError(f"Unknown RAG_RETRIEVER_BACKEND: {settings.RAG_RETRIEVER_BACKEND!r}")


def get_reranker() -> Reranker | None:
    if not settings.RAG_RERANKER_ENABLED:
        return None

    if settings.RAG_RERANKER_BACKEND == "local":
        from app.rag.retrieval.rerankers.cross_encoder_reranker import CrossEncoderReranker

        return CrossEncoderReranker(
            model_path=require_local_model(settings.RAG_RERANKER_MODEL),
            device=settings.RAG_RERANKER_DEVICE,
        )

    if settings.RAG_RERANKER_BACKEND == "api":
        api_key = settings.RAG_RERANKER_API_KEY.get_secret_value()
        if settings.RAG_RERANKER_API_PROVIDER == "cohere":
            from app.rag.retrieval.rerankers.cohere_reranker import CohereReranker

            return CohereReranker(api_key, settings.RAG_RERANKER_API_MODEL, settings.RAG_RERANKER_API_TIMEOUT)
        if settings.RAG_RERANKER_API_PROVIDER == "voyage":
            from app.rag.retrieval.rerankers.voyage_reranker import VoyageReranker

            return VoyageReranker(api_key, settings.RAG_RERANKER_API_MODEL, settings.RAG_RERANKER_API_TIMEOUT)
        raise ValueError(f"Unknown RAG_RERANKER_API_PROVIDER: {settings.RAG_RERANKER_API_PROVIDER!r}")

    raise ValueError(f"Unknown RAG_RERANKER_BACKEND: {settings.RAG_RERANKER_BACKEND!r}")