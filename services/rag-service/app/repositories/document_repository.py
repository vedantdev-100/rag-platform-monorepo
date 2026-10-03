import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document


class DocumentRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, document: Document) -> Document:
        self.session.add(document)
        await self.session.commit()
        await self.session.refresh(document)
        return document

    async def get_by_id(self, document_id: uuid.UUID) -> Document | None:
        result = await self.session.execute(select(Document).where(Document.id == document_id))
        return result.scalar_one_or_none()

    async def list_by_owner(self, owner_id: uuid.UUID, *, limit: int = 20, offset: int = 0) -> list[Document]:
        result = await self.session.execute(
            select(Document)
            .where(Document.owner_id == owner_id)
            .order_by(Document.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def update_status(self, document: Document, status: str) -> Document:
        document.status = status
        await self.session.commit()
        await self.session.refresh(document)
        return document

    async def update_metadata(self, document: Document, metadata: dict) -> Document:
        # Assign a NEW dict: SQLAlchemy doesn't detect in-place mutation of a
        # JSONB value, so mutating doc_metadata directly would not persist.
        document.doc_metadata = {**(document.doc_metadata or {}), **metadata}
        await self.session.commit()
        await self.session.refresh(document)
        return document

    async def delete(self, document: Document) -> None:
        await self.session.delete(document)  # cascades to chunks (ondelete="CASCADE")
        await self.session.commit()
