"""Reserve identity before writing bytes; acceptance commits job + ready source."""
import hashlib
import mimetypes
import uuid
from datetime import timedelta

from app.core.config import get_settings
from app.events.source_cleanup import lock_owner
from app.rag.ingestion.storage import object_location
from app.workflows.policy import processing_version
from app.workflows.state import abort_upload, queue_document
from rag_persistence.models.document import Document
from rag_persistence.utils import utcnow


class UploadRejected(Exception):
    pass


async def submit(session, storage, *, owner_id, filename, source_type, content):
    settings = get_settings()
    owner_id = uuid.UUID(str(owner_id))
    document_id, upload_token, job_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    uri = storage.allocate(filename, document_id, owner_id)
    location = object_location(uri)
    upload_expires_at = utcnow() + timedelta(seconds=settings.UPLOAD_RESERVATION_SECONDS)
    # Transaction 1 durably records every location before a write can occur.
    try:
        owner = await lock_owner(session, owner_id)
        if owner.is_deleted:
            raise UploadRejected("Owner has been deleted")
        document = Document(
            id=document_id, owner_id=owner_id, title=filename, source_type=source_type,
            source_uri=uri, object_bucket=location[0] if location else None,
            object_key=location[1] if location else None, status="pending",
            checksum=hashlib.sha256(content).hexdigest(), file_size_bytes=len(content),
            mime_type=mimetypes.guess_type(filename)[0] or "application/octet-stream",
            generation=1, processing_version=processing_version(settings), job_id=job_id,
            processing_token=upload_token,
            processing_lease_until=upload_expires_at,
            doc_metadata={"source_ready": False},
        )
        session.add(document)
        await session.commit()
    except BaseException:
        await session.rollback()
        raise
    try:
        # No DB transaction remains open during this bounded storage write.
        await storage.write(uri, content, filename)
        owner = await lock_owner(session, owner_id)
        from sqlalchemy import select
        document = (await session.execute(select(Document).where(Document.id == document_id)
                    .with_for_update().execution_options(populate_existing=True))).scalar_one_or_none()
        if (owner.is_deleted or document is None or document.processing_token != upload_token
                or document.status != "pending" or document.processing_lease_until <= utcnow()):
            raise UploadRejected("Upload reservation expired or owner was deleted")
        document.doc_metadata = {**document.doc_metadata, "source_ready": True}
        document.processing_token = None
        document.processing_lease_until = None
        await queue_document(session, document)
        await session.commit()
        return document
    except BaseException:
        await session.rollback()
        try:
            await abort_upload(document_id, owner_id, upload_token, uri, "upload_not_accepted",
                               not_before=upload_expires_at + timedelta(seconds=30))
        except Exception:
            # The durable reservation still lets reconciliation recover after
            # DB connectivity returns. Do not delete blindly after a lost commit response.
            from app.logging import get_logger
            get_logger(__name__).error("upload_abort_record_failed", document_id=str(document_id))
        raise
