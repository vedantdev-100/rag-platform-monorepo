def build_strategy(name, settings, retriever, provider):
    # Import lazily: ingestion worker and disabled API need no LangGraph installation.
    if name == "standard":
        from app.rag.generation.strategies.standard import build_standard

        return build_standard(settings, retriever, provider)
    raise ValueError("Strategy has not been implemented: " + name)
