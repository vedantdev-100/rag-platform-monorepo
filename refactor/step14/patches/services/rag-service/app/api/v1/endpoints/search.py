"""Owner-scoped search through the reusable retrieval orchestration service."""
from fastapi import APIRouter, Depends, HTTPException, Request
from platform_auth import AuthenticatedUser, require_scopes
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.rate_limit import limiter
from app.db.session import get_db_session
from app.exceptions import RetrievalError
from app.rag.embeddings.client import EmbeddingServiceError
from app.rag.retrieval.factory import get_retrieval_service
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
    service = get_retrieval_service(ChunkRepository(session))
    try:
        outcome = await service.retrieve(session, payload.query,
                                         owner_id=str(current_user.id), top_k=payload.top_k)
    except EmbeddingServiceError:
        raise HTTPException(status_code=503, detail="embedding_service_unavailable") from None
    except RetrievalError:
        raise HTTPException(status_code=503, detail="reranking_service_unavailable") from None
    return SearchResponse(
        query=outcome.query,
        results=[SearchResultOut(**result.__dict__) for result in outcome.results],
        retriever_backend=outcome.retriever_backend,
        reranked=outcome.reranked,
    )
