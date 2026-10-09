import asyncio
import json
import uuid
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from pydantic import ValidationError
from platform_auth import AuthenticatedUser
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from app.chat.memory import bounded_history, standalone_question
from app.chat.schemas import ChatTurn, CreateConversation, SelectDocuments, UpdateConversation
from app.chat.service import ChatService
from app.chat.events import chat_events
from app.rag.generation.context import build_context, size
from app.rag.generation.service import GenerationService, noop, reserve
from app.rag.generation.types import GenerationError, ProviderResult
from app.tests.unit.test_generation import cfg, chunk
from rag_persistence.models.conversation import Conversation, GenerationRun, ChatMessage
from rag_persistence.repositories.chunk_repository import ChunkRepository

@pytest.mark.parametrize('body',[
    {'query':' ', 'client_message_id':str(uuid.uuid4())},
    {'query':'q','client_message_id':'not-a-uuid'},
    {'query':'q','client_message_id':str(uuid.uuid4()),'owner_id':'other'},
    {'query':'q','client_message_id':str(uuid.uuid4()),'top_k':True},
    {'query':'q','client_message_id':str(uuid.uuid4()),'top_k':51},
])
def test_turn_validation(body):
    with pytest.raises(ValidationError): ChatTurn(**body)

def test_conversation_validation():
    assert CreateConversation().document_scope == 'selected'
    with pytest.raises(ValidationError): CreateConversation(title=' ')
    with pytest.raises(ValidationError): UpdateConversation(title=' ')
    uid=uuid.uuid4()
    with pytest.raises(ValidationError): SelectDocuments(document_ids=[uid,uid])

def test_history_preserves_whole_pairs_and_strips_old_labels():
    history=bounded_history([('old','a [S1]'),('latest','b [S2]')],2,1000)
    assert history == [{'role':'user','content':'latest'},{'role':'assistant','content':'b '}]
    assert bounded_history([('🌍'*1000,'a')],12,100)==[]

def test_context_budget_includes_history_and_evidence():
    settings=cfg(RAG_CONTEXT_MAX_BYTES=2000)
    history=[{'role':'user','content':'Earlier question'},{'role':'assistant','content':'Earlier reply'}]
    messages,sources=build_context('When?', [chunk('🌍'*5000)], settings,history=history)
    assert size(messages)<=2000 and sources
    assert 'never evidence' in messages[1]['content']

class Provider:
    def __init__(self): self.calls=[]
    async def generate(self,messages,emit):
        self.calls.append(messages)
        if 'Resolve the latest' in messages[0]['content']:
            return ProviderResult('When did Mira take ownership of Atlas?',None,'stop')
        await emit('delta',{'text':'Mira [S1]','provisional':True})
        return ProviderResult('Mira [S1]',None,'stop')
    async def close(self): pass

class Retriever:
    def __init__(self): self.calls=[]
    async def retrieve(self,query,**kwargs):
        self.calls.append((query,kwargs))
        return [chunk()]

@pytest.mark.asyncio
async def test_multiturn_resolves_retrieval_and_keeps_original_question():
    retriever,provider=Retriever(),Provider()
    history=[{'role':'user','content':'Who owns Atlas?'},{'role':'assistant','content':'Mira'}]
    service=GenerationService(cfg(),retriever,provider)
    ids=[uuid.uuid4()]
    result=await service.run('When did she take ownership?','owner',history=history,
                             document_ids=ids,conversation_id='chat-a')
    assert result.status=='answered'
    assert retriever.calls[0][0]=='When did Mira take ownership of Atlas?'
    assert retriever.calls[0][1]['document_ids']==ids
    assert 'When did she take ownership?' in provider.calls[-1][1]['content']

@pytest.mark.asyncio
async def test_first_turn_does_not_call_rewriter():
    provider=Provider()
    assert await standalone_question(provider,'q',[])=='q' and not provider.calls

@pytest.mark.asyncio
async def test_bad_rewriter_fails_before_retrieval():
    class Bad(Provider):
        async def generate(self,*a): return ProviderResult(' ',None,'stop')
    r=Retriever()
    with pytest.raises(GenerationError,match='query_resolution_failed'):
        await GenerationService(cfg(),r,Bad()).run('q','o',history=[{'role':'user','content':'x'}],conversation_id='c')
    assert not r.calls

@pytest.mark.asyncio
async def test_scoped_sql_filters_before_limits_in_both_searches():
    class Result:
        def all(self): return []
    class Session:
        def __init__(self): self.queries=[]
        async def execute(self,q): self.queries.append(q); return Result()
    s=Session(); ids=[uuid.uuid4()]; owner=uuid.uuid4()
    repo=ChunkRepository(s,default_top_k=5,document_ids=ids)
    await repo.similarity_search([0.]*768,owner_id=owner)
    await repo.keyword_search('q',owner_id=owner)
    for q in s.queries:
        compiled=q.compile(dialect=postgresql.dialect())
        sql=str(compiled)
        assert 'owner_id =' in sql and 'status =' in sql and 'documents.id IN' in sql
        assert any(value==ids for value in compiled.params.values())
    s.queries=[]
    repo=ChunkRepository(s,default_top_k=5,document_ids=[])
    await repo.keyword_search('q',owner_id=owner)
    assert [] in s.queries[0].compile(dialect=postgresql.dialect()).params.values()

def test_schema_cascades_and_running_uniqueness():
    sql=str(CreateTable(ChatMessage.__table__).compile(dialect=postgresql.dialect()))
    assert sql.count('ON DELETE CASCADE')==2
    sql='\n'.join(str(CreateIndex(i).compile(dialect=postgresql.dialect())) for i in GenerationRun.__table__.indexes)
    assert 'CREATE UNIQUE INDEX uq_chat_active_run' in sql and "status = 'running'" in sql
    assert Conversation.__table__.schema=='rag'

class Repo:
    def __init__(self): self.writes=[]; self.pulses=0; self.reject_finish=False
    async def pulse(self,*args): self.pulses+=1
    async def finish(self,*args):
        if self.reject_finish: raise GenerationError('evidence_unavailable',409)
        self.writes.append(('completed',args[-1]))
        return {'status':'completed','messages':[],'run_id':str(args[2])}
    async def fail(self,*args): self.writes.append((args[3],args[4]))

def turn():
    return {'run_id':str(uuid.uuid4()),'client_message_id':str(uuid.uuid4()),
            'messages':[{'id':'u'},{'id':'a'}],'history':[],'document_ids':[]}

def payload(): return ChatTurn(query='q',client_message_id=uuid.uuid4())

@pytest.mark.asyncio
async def test_sse_done_after_commit():
    repo=Repo(); generation=GenerationService(cfg(),Retriever(),Provider())
    service=ChatService(repo,generation); lease=await reserve(generation.capacity)
    events=[]
    async for event in chat_events(service,lease,turn(),payload(),uuid.uuid4(),uuid.uuid4(),noop):
        if 'event: done' in event: assert repo.writes[0][0]=='completed'
        events.append(event)
    assert 'event: start' in events[0] and 'event: done' in events[-1]
    assert 'conversation_id' in events[-1] and lease.released

@pytest.mark.asyncio
async def test_finalization_error_discards_provisional():
    repo=Repo(); repo.reject_finish=True
    generation=GenerationService(cfg(),Retriever(),Provider());lease=await reserve(generation.capacity)
    events=[e async for e in chat_events(ChatService(repo,generation),lease,turn(),payload(),uuid.uuid4(),uuid.uuid4(),noop)]
    assert 'event: error' in events[-1] and 'discard_provisional' in events[-1]
    assert not any('event: done' in e for e in events)
    assert repo.writes[-1][0]=='failed'

@pytest.mark.asyncio
async def test_stream_close_records_cancellation_and_releases_capacity():
    started,stopped=asyncio.Event(),asyncio.Event()
    class Blocking(Provider):
        async def generate(self,messages,emit):
            started.set()
            try: await asyncio.Event().wait()
            finally: stopped.set()
    repo=Repo();generation=GenerationService(cfg(),Retriever(),Blocking());lease=await reserve(generation.capacity)
    stream=chat_events(ChatService(repo,generation),lease,turn(),payload(),uuid.uuid4(),uuid.uuid4(),noop)
    await anext(stream)
    await asyncio.wait_for(started.wait(),2)
    await stream.aclose()
    assert stopped.is_set() and lease.released and repo.writes[-1][0]=='cancelled'

@pytest.mark.asyncio
async def test_api_replay_never_calls_provider(monkeypatch):
    from app.api.v1.endpoints import conversations as endpoint
    app=FastAPI();app.include_router(endpoint.router,prefix='/api/v1')
    owner=uuid.uuid4();cid=uuid.uuid4();p=Provider()
    app.dependency_overrides[endpoint.user_dependency]=lambda: AuthenticatedUser(id=str(owner),role='user',scopes=['rag:query'])
    class ReplayRepo:
        async def begin(self,*args): return {'replay':True,'status':'running','run_id':str(uuid.uuid4()),
            'conversation_id':str(cid),'client_message_id':str(uuid.uuid4()),'messages':[]}
    app.state.chat_repository=ReplayRepo()
    app.state.generation_service=GenerationService(cfg(),Retriever(),p)
    monkeypatch.setattr(endpoint,'authorization_guard',lambda *args:noop)
    monkeypatch.setattr(endpoint.limiter,'enabled',False)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        body={'query':'q','client_message_id':str(uuid.uuid4())}
        r=await client.post(f'/api/v1/conversations/{cid}/messages',json=body)
        assert r.status_code==200 and r.json()['replay']
        r=await client.post(f'/api/v1/conversations/{cid}/messages/stream',json=body)
        assert r.status_code==200 and 'event: replay' in r.text
        assert not p.calls and app.state.generation_service.capacity._value==2
