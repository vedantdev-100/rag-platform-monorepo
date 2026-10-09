"""Upload acceptance and owner-scoped status polling; models run in the worker."""
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, Response, UploadFile
from platform_auth import AuthenticatedUser, require_scopes
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.rate_limit import limiter
from app.db.session import get_db_session
from app.exceptions import FileTooLargeError
from app.rag.ingestion.source_types import SUPPORTED_SOURCE_TYPES, detect_source_type
from app.rag.ingestion.storage import StorageWriteError
from app.rag.ingestion.storage_factory import build_file_storage
from app.repositories.document_repository import DocumentRepository
from app.schemas.document import DocumentListOut
from app.schemas.ingestion import DocumentJobOut
from app.workflows.submission import UploadRejected, submit

router = APIRouter(prefix="/documents", tags=["documents"])
settings = get_settings()
_READ_CHUNK_BYTES = 1024 * 1024


async def _read_capped(file: UploadFile, max_bytes: int) -> bytes:
    data = bytearray()
    while piece := await file.read(_READ_CHUNK_BYTES):
        data.extend(piece)
        if len(data) > max_bytes:
            raise FileTooLargeError(f"File exceeds the {settings.RAG_MAX_UPLOAD_MB} MB upload limit")
    return bytes(data)


@router.post("", response_model=DocumentJobOut, status_code=202)
@limiter.limit(settings.RATE_LIMIT_UPLOAD)
async def upload_document(
    request: Request, response: Response, file: UploadFile,
    current_user: AuthenticatedUser = Depends(require_scopes("rag:ingest")),
    session: AsyncSession = Depends(get_db_session),
):
    filename = Path((file.filename or "upload").replace("\\", "/")).name
    source_type = detect_source_type(filename)
    if not filename or len(filename) > 500 or source_type not in SUPPORTED_SOURCE_TYPES:
        raise HTTPException(422, "Unsupported filename/type; use PDF, DOCX, PPTX, HTML, Markdown or text")
    content = await _read_capped(file, settings.RAG_MAX_UPLOAD_MB * 1024 * 1024)
    if not content:
        raise HTTPException(422, "Empty files are not supported")
    try:
        document = await submit(session, build_file_storage(), owner_id=current_user.id,
                                filename=filename, source_type=source_type, content=content)
    except StorageWriteError as exc:
        raise HTTPException(503, "Source storage unavailable; upload was not accepted") from exc
    except UploadRejected as exc:
        raise HTTPException(409, str(exc)) from exc
    response.headers["Location"] = request.url.path.rstrip("/") + "/" + str(document.id)
    response.headers["Retry-After"] = "2"
    return document


@router.get("", response_model=DocumentListOut)
async def list_documents(
    current_user: AuthenticatedUser = Depends(require_scopes("rag:query")),
    session: AsyncSession = Depends(get_db_session), limit: int = 20, offset: int = 0,
):
    documents = await DocumentRepository(session).list_by_owner(uuid.UUID(str(current_user.id)),
                                                               limit=limit, offset=offset)
    return DocumentListOut(documents=documents, total=len(documents))


@router.get("/{document_id}", response_model=DocumentJobOut, name="get_document_status")
async def get_document_status(
    document_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(require_scopes("rag:query")),
    session: AsyncSession = Depends(get_db_session),
):
    document = await DocumentRepository(session).get_by_id(document_id)
    if document is None or document.owner_id != uuid.UUID(str(current_user.id)):
        raise HTTPException(404, "Document not found")
    return document


@router.get('/{document_id}/chunks/{chunk_id}')
async def source_excerpt(document_id: uuid.UUID, chunk_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(require_scopes('rag:query')),
    session: AsyncSession = Depends(get_db_session),
):
    from sqlalchemy import select
    from rag_persistence.models.chunk import Chunk
    from rag_persistence.models.document import Document
    row = (await session.execute(select(Chunk, Document.title).join(Document, Chunk.document_id == Document.id)
        .where(Chunk.id == chunk_id, Document.id == document_id,
               Document.owner_id == uuid.UUID(str(current_user.id)), Document.status == 'ingested'))).one_or_none()
    if row is None: raise HTTPException(404, 'Source not found')
    chunk, title = row
    import json
    return {'document_id': str(document_id), 'chunk_id': str(chunk_id), 'title': title,
            'content': chunk.content[:20000], 'truncated': len(chunk.content) > 20000,
            'metadata': {k: v for k, v in chunk.chunk_metadata.items()
                         if k in {'page','pages','page_number','page_numbers','heading','headings'}
                         and len(json.dumps(v, default=str)) <= 1000}}


@router.delete('/{document_id}', status_code=204)
@limiter.limit(settings.RATE_LIMIT_UPLOAD)
async def delete_document(request: Request, document_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(require_scopes('rag:ingest')),
):
    from sqlalchemy import delete, select
    from app.db.session import AsyncSessionLocal
    from app.events.source_cleanup import enqueue_cleanup, lock_owner
    from rag_persistence.models.document import Document
    owner = uuid.UUID(str(current_user.id))
    async with AsyncSessionLocal() as session, session.begin():
        state = await lock_owner(session, owner)
        if state.is_deleted: raise HTTPException(401, 'Account unavailable')
        doc = (await session.scalars(select(Document).where(Document.id == document_id,
               Document.owner_id == owner).with_for_update())).one_or_none()
        if doc is None: raise HTTPException(404, 'Document not found')
        # Only delete completed/failed uploads; an in-flight object PUT must finish first.
        if doc.status not in {'ingested', 'failed'}: raise HTTPException(409, 'Document is still processing')
        await enqueue_cleanup(session, doc.source_uri, document_id=document_id, owner_id=owner)
        await session.execute(delete(Document).where(Document.id == doc.id))
    return Response(status_code=204)
