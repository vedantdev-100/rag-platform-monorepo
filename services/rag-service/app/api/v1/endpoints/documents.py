"""Only the auth import changed from the monolith version the scope
check itself (`require_scopes("rag:ingest")`) is identical."""
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from platform_auth import AuthenticatedUser, require_scopes
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.rate_limit import limiter
from app.db.session import get_db_session
from app.exceptions import FileTooLargeError
from app.rag.ingestion.factory import get_chunker, get_document_parser, get_embedding_generator, get_file_storage
from app.rag.ingestion.pipeline import IngestionService
from app.rag.ingestion.source_types import detect_source_type
from app.rag.ingestion.storage import StorageWriteError
from app.repositories.chunk_repository import ChunkRepository
from app.repositories.document_repository import DocumentRepository
from app.schemas.document import DocumentListOut, DocumentOut

router = APIRouter(prefix="/documents", tags=["documents"])
settings = get_settings()
_READ_CHUNK_BYTES = 1024 * 1024


def get_ingestion_service(session: AsyncSession = Depends(get_db_session)) -> IngestionService:
    return IngestionService(
        storage=get_file_storage(), parser=get_document_parser(), chunker=get_chunker(),
        embedder=get_embedding_generator(), document_repo=DocumentRepository(session),
        chunk_repo=ChunkRepository(session),
    )


async def _read_capped(file: UploadFile, max_bytes: int) -> bytes:
    data = bytearray()
    while piece := await file.read(_READ_CHUNK_BYTES):
        data.extend(piece)
        if len(data) > max_bytes:
            raise FileTooLargeError(f"File exceeds the {settings.RAG_MAX_UPLOAD_MB} MB upload limit")
    return bytes(data)


@router.post("", response_model=DocumentOut, status_code=201)
@limiter.limit(settings.RATE_LIMIT_UPLOAD)
async def upload_document(
    request: Request,
    file: UploadFile,
    current_user: AuthenticatedUser = Depends(require_scopes("rag:ingest")),
    service: IngestionService = Depends(get_ingestion_service),
):
    filename = Path(file.filename or "upload").name
    content = await _read_capped(file, settings.RAG_MAX_UPLOAD_MB * 1024 * 1024)
    try:
        return await service.ingest(
            owner_id=current_user.id, filename=filename, content=content,
            source_type=detect_source_type(filename),
        )
    except StorageWriteError as exc:
        raise HTTPException(status_code=503, detail="Source storage is unavailable; try again later") from exc


@router.get("", response_model=DocumentListOut)
async def list_documents(
    current_user: AuthenticatedUser = Depends(require_scopes("rag:query")),
    session: AsyncSession = Depends(get_db_session),
    limit: int = 20,
    offset: int = 0,
):
    repo = DocumentRepository(session)
    documents = await repo.list_by_owner(current_user.id, limit=limit, offset=offset)
    return DocumentListOut(documents=documents, total=len(documents))
