"""Real PostgreSQL + configured storage check, using only disposable rows.

Stop rag-service before running so its cleanup loop cannot race this check.
No auth user or Redis stream event is created; _handle is called directly.
"""
import asyncio
import os
import uuid
from datetime import timedelta

from botocore.exceptions import ClientError
from sqlalchemy import delete, select, update

from app.db.session import AsyncSessionLocal
from app.events.consumer import UserEventConsumer
from app.events.source_cleanup import cleanup_once, enqueue_cleanup
from app.rag.ingestion.storage_factory import build_file_storage
from rag_persistence.models.document import Document
from rag_persistence.models.outbox import OutboxMessage
from rag_persistence.models.user_lifecycle_state import UserLifecycleState
from rag_persistence.utils import utcnow


class ForcedRollback(Exception):
    pass


class OfflineStorage:
    async def delete(self, uri):
        raise OSError("simulated storage outage")


async def main():
    owner_id, document_id = uuid.uuid4(), uuid.uuid4()
    storage = build_file_storage()
    uri = await storage.save(b"Disposable Step 7 cleanup source", "step07-cleanup.txt")
    consumer = UserEventConsumer(os.environ["REDIS_URL"], "unused-step07-test", "unused-step07-test")
    try:
        async with AsyncSessionLocal() as session:
            async with session.begin():
                session.add(Document(id=document_id, owner_id=owner_id, title="step07-cleanup.txt",
                                     source_type="text", source_uri=uri, status="failed"))
        try:
            async with AsyncSessionLocal() as session:
                async with session.begin():
                    await enqueue_cleanup(session, uri, document_id=document_id, owner_id=owner_id)
                    await session.execute(delete(Document).where(Document.id == document_id))
                    raise ForcedRollback()
        except ForcedRollback:
            pass
        async with AsyncSessionLocal() as session:
            assert await session.get(Document, document_id) is not None, "Deletion escaped rollback"
            assert await session.scalar(select(OutboxMessage.id).where(OutboxMessage.owner_id == owner_id)) is None, "Intent escaped rollback"
        assert await storage.read(uri), "Source disappeared during DB rollback"
        print("Document deletion and cleanup intent roll back together: OK")

        await consumer._handle({"event": "user.deactivated", "user_id": str(owner_id)}, "step07-deactivated")
        async with AsyncSessionLocal() as session:
            assert await session.get(Document, document_id) is not None
        assert await storage.read(uri)
        print("Deactivation preserves document and source: OK")

        await consumer._handle({"event": "user.deleted", "user_id": str(owner_id)}, "step07-deleted")
        async with AsyncSessionLocal() as session:
            assert await session.get(Document, document_id) is None, "Document not deleted"
            assert (await session.get(UserLifecycleState, owner_id)).is_deleted, "Deletion fence missing"
            message = (await session.execute(select(OutboxMessage).where(OutboxMessage.owner_id == owner_id))).scalar_one()
            assert message.status == "pending", "Stop running cleanup consumers before this test"
            message_id = message.id
        assert await cleanup_once(OfflineStorage(), source_uri=uri)
        async with AsyncSessionLocal() as session:
            message = await session.get(OutboxMessage, message_id)
            assert message.status == "pending" and message.attempts == 1
            assert message.last_error == "OSError"
        assert await storage.read(uri), "Failed deletion should keep the source for retry"
        print("Storage outage preserves a durable pending cleanup intent: OK")

        async with AsyncSessionLocal() as session:
            async with session.begin():
                await session.execute(update(OutboxMessage).where(OutboxMessage.id == message_id).values(
                    available_at=utcnow() - timedelta(seconds=1)))
        assert await cleanup_once(storage, source_uri=uri)
        async with AsyncSessionLocal() as session:
            assert (await session.get(OutboxMessage, message_id)).status == "published"
        try:
            await storage.read(uri)
        except FileNotFoundError:
            pass
        except ClientError as exc:
            assert exc.response["Error"]["Code"] in {"404", "NoSuchKey", "NotFound"}
        else:
            raise AssertionError("Source still exists after successful cleanup")
        await consumer._handle({"event": "user.deleted", "user_id": str(owner_id)}, "step07-deleted-replay")
        print("Retry deletes source; repeated user deletion remains safe: OK")
    finally:
        await consumer.stop()
        # Idempotent source removal and cleanup of ONLY this random test owner.
        try:
            await storage.delete(uri)
        finally:
            async with AsyncSessionLocal() as session:
                async with session.begin():
                    await session.execute(delete(Document).where(Document.owner_id == owner_id))
                    await session.execute(delete(OutboxMessage).where(OutboxMessage.owner_id == owner_id))
                    await session.execute(delete(UserLifecycleState).where(UserLifecycleState.user_id == owner_id))


if __name__ == "__main__":
    asyncio.run(main())
