"""Read-only rollout gate. Stop API uploads before running; worker drains jobs."""
import asyncio
from sqlalchemy import func, select
from rag_persistence.models import Document
from app.db.session import AsyncSessionLocal, engine

async def main():
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(Document.status, func.count()).where(
                Document.status.in_(['pending', 'processing'])).group_by(Document.status))
            counts = dict(result.all())
        print('Active documents:', counts or 'none')
        if counts:
            raise SystemExit('Keep the existing worker running until these jobs are terminal. Do not switch yet.')
        print('Queue rollout gate: OK (no pending/processing documents)')
    finally:
        await engine.dispose()

if __name__ == '__main__':
    asyncio.run(main())
