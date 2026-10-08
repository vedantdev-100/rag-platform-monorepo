"""Shared validation for search and the future generation entry point."""
def normalize_query(query: str) -> str:
    if not isinstance(query, str) or len(query) > 2000:
        raise ValueError("Query must be a string of at most 2000 characters")
    query = query.strip()
    if not query:
        raise ValueError("Query must contain non-whitespace text")
    return query
