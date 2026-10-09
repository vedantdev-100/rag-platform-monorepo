"""PostgreSQL acceptance checks. No provider calls. Default mode rolls fixtures back.

--concurrency uses independent connections and transient committed synthetic rows,
then deletes them; run against a development database after the chat migration.
"""
import argparse
import asyncio
import uuid
from datetime import timedelta

from sqlalchemy import delete, select, func
from sqlalchemy.ext.asyncio import async_sessionmaker
from app.chat.repository import ChatRepository, ChatError
from app.chat.schemas import CreateConversation, SelectDocuments, ChatTurn
from app.db.session import engine, AsyncSessionLocal
from app.rag.generation.types import Answer, Source, GenerationError
from rag_persistence.models.conversation import Conversation, ChatMessage, GenerationRun
from rag_persistence.models.document import Document
from rag_persistence.models.user_lifecycle_state import UserLifecycleState
from rag_persistence.utils import utcnow

async def rejected(awaitable, code):
    try: await awaitable
    except (ChatError,GenerationError) as exc:
        assert exc.code == code, (exc.code, code)
    else: raise AssertionError(f'Expected {code}')

async def rollback_probe():
    async with engine.connect() as connection:
        transaction = await connection.begin()
        sessions = async_sessionmaker(connection,expire_on_commit=False,join_transaction_mode='create_savepoint')
        repo = ChatRepository(sessions)
        owner,other=uuid.uuid4(),uuid.uuid4()
        try:
            async with sessions() as s,s.begin():
                doc=Document(owner_id=owner,title='Chat acceptance fixture',source_type='text',status='ingested')
                alien=Document(owner_id=other,title='Isolation fixture',source_type='text',status='ingested')
                s.add_all([doc,alien]);await s.flush();did,alienid=doc.id,alien.id
            c=await repo.create(owner,CreateConversation());cid=uuid.UUID(c['id'])
            await rejected(repo.get(other,cid),'conversation_not_found')
            await rejected(repo.select_documents(owner,cid,SelectDocuments(document_ids=[alienid])),'document_not_found')
            await repo.select_documents(owner,cid,SelectDocuments(document_ids=[did]))
            payload=ChatTurn(query='Who owns Atlas?',client_message_id=uuid.uuid4())
            turn=await repo.begin(owner,cid,payload);rid=uuid.UUID(turn['run_id'])
            assert turn['document_ids']==[did] and not turn['history']
            assert (await repo.begin(owner,cid,payload))['replay']
            await rejected(repo.begin(owner,cid,ChatTurn(query='Different',client_message_id=payload.client_message_id)), 'idempotency_conflict')
            await rejected(repo.begin(owner,cid,ChatTurn(query='Different',client_message_id=uuid.uuid4())), 'conversation_busy')
            await repo.pulse(owner,cid,rid)
            answer=Answer(request_id=str(rid),status='answered',answer='Mira [S1]',
                sources=[Source(label='S1',document_id=str(did),chunk_id=str(uuid.uuid4()),modality='text')],provider='probe',model='probe')
            await repo.finish(owner,cid,rid,answer)
            replay=await repo.begin(owner,cid,payload)
            assert replay['status']=='completed' and replay['messages'][1]['answer']['answer']=='Mira [S1]'
            # New repository object reloads persisted history.
            repo=ChatRepository(sessions)
            next_payload=ChatTurn(query='When did she take ownership?',client_message_id=uuid.uuid4())
            next_turn=await repo.begin(owner,cid,next_payload);next_rid=uuid.UUID(next_turn['run_id'])
            assert len(next_turn['history'])==2 and next_turn['history'][1]['content']=='Mira '
            await repo.fail(owner,cid,next_rid,'cancelled','generation_cancelled')
            await rejected(repo.finish(owner,cid,next_rid,answer),'generation_cancelled')
            p3=ChatTurn(query='q',client_message_id=uuid.uuid4());t3=await repo.begin(owner,cid,p3)
            async with sessions() as s,s.begin():
                run=await s.get(GenerationRun,uuid.UUID(t3['run_id']));run.lease_until=utcnow()-timedelta(seconds=1)
            assert (await repo.begin(owner,cid,p3))['status']=='cancelled'
            assert (await repo.history(owner,cid,50))['items'][-1]['status']=='cancelled'
            # User deletion removes all chat data using the same FK cascade as consumer.
            async with sessions() as s,s.begin():
                await s.execute(delete(Conversation).where(Conversation.owner_id==owner))
            async with sessions() as s:
                assert not await s.scalar(select(func.count()).select_from(ChatMessage).where(ChatMessage.conversation_id==cid))
                assert not await s.scalar(select(func.count()).select_from(GenerationRun).where(GenerationRun.conversation_id==cid))
            print('Chat PostgreSQL repository acceptance: PASSED (fixtures rolled back)')
        finally:
            await transaction.rollback()

async def concurrency_probe():
    owner=uuid.uuid4();repo=ChatRepository(AsyncSessionLocal)
    try:
        c=await repo.create(owner,CreateConversation());cid=uuid.UUID(c['id'])
        payloads=[ChatTurn(query='q',client_message_id=uuid.uuid4()) for _ in range(2)]
        results=await asyncio.gather(*(repo.begin(owner,cid,p) for p in payloads),return_exceptions=True)
        wins=[r for r in results if isinstance(r,dict)]
        failures=[r for r in results if isinstance(r,ChatError)]
        assert len(wins)==1 and len(failures)==1 and failures[0].code=='conversation_busy', results
        rid=uuid.UUID(wins[0]['run_id'])
        await repo.fail(owner,cid,rid,'cancelled','generation_cancelled')
        await rejected(repo.pulse(owner,cid,rid),'generation_cancelled')
        print('Chat PostgreSQL concurrent submission and fencing: PASSED')
    finally:
        async with AsyncSessionLocal() as s,s.begin():
            await s.execute(delete(Conversation).where(Conversation.owner_id==owner))
            await s.execute(delete(UserLifecycleState).where(UserLifecycleState.user_id==owner))

async def main(concurrency):
    try:
        await rollback_probe()
        if concurrency: await concurrency_probe()
    finally: await engine.dispose()

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--concurrency',action='store_true')
    asyncio.run(main(parser.parse_args().concurrency))
