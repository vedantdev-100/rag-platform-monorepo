"""Only the auth import changed from the version given earlier in chat."""
from fastapi import APIRouter, Depends, Request
from platform_auth import AuthenticatedUser, require_scopes
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.rate_limit import limiter
from app.db.session import get_db_session
from app.rag.retrieval.factory import get_reranker, get_retriever
from app.repositories.chunk_repository import ChunkRepository
from app.schemas.search import SearchRequest, SearchResponse, SearchResultOut

router = APIRouter(prefix="/documents", tags=["search"])
settings = get_settings()


@router.post("/search", response_model=SearchResponse)
@limiter.limit(settings.RATE_LIMIT_SEARCH)
async def search_documents(
    request: Request,
    payload: SearchRequest,
    current_user: AuthenticatedUser = Depends(require_scopes("rag:query")),
    session: AsyncSession = Depends(get_db_session),
):
    chunk_repo = ChunkRepository(session)
    retriever = get_retriever(chunk_repo)
    reranker = get_reranker()

    candidate_count = settings.RAG_RETRIEVAL_CANDIDATES if reranker else payload.top_k
    results = await retriever.retrieve(payload.query, owner_id=str(current_user.id), top_k=candidate_count)

    reranked = False
    if reranker and results:
        top_n = payload.top_k or settings.RAG_RERANKER_TOP_N
        results = await reranker.rerank(payload.query, results, top_n=top_n)
        reranked = True
    elif payload.top_k:
        results = results[: payload.top_k]

    return SearchResponse(
        query=payload.query,
        results=[SearchResultOut(**r.__dict__) for r in results],
        retriever_backend=settings.RAG_RETRIEVER_BACKEND,
        reranked=reranked,
    )
