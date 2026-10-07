"""Fail at startup if a slim container is configured to load local models."""
def validate_runtime_role(settings):
    role = settings.RAG_RUNTIME_ROLE
    if role == "development":
        return settings
    if settings.RAG_EMBEDDING_BACKEND != "http":
        raise ValueError("Slim API/worker images require RAG_EMBEDDING_BACKEND=http")
    if settings.RAG_PARSER_BACKEND != "docling_serve":
        raise ValueError("Slim API/worker images require RAG_PARSER_BACKEND=docling_serve")
    if settings.RAG_RERANKER_ENABLED and settings.RAG_RERANKER_BACKEND == "local":
        raise ValueError("Local reranking requires the local-models extra; use an API reranker in slim images")
    if settings.RUN_LIFECYCLE_CONSUMER != (role == "worker"):
        raise ValueError("RUN_LIFECYCLE_CONSUMER must be false for api and true for worker")
    return settings
