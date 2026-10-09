"""Short transactions with owner-lock ordering and durable generation leases."""
import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import delete, select
from app.chat.memory import bounded_history
from app.chat.settings import get_chat_settings
from app.events.source_cleanup import lock_owner
from app.rag.generation.types import GenerationError
from rag_persistence.models.conversation import Conversation, ConversationDocument, ChatMessage, GenerationRun
from rag_persistence.models.document import Document
from rag_persistence.utils import utcnow

@dataclass
class ChatError(Exception):
    code: str
    status: int = 409


def conversation_out(c, documents=None):
    return {'id': str(c.id), 'title': c.title, 'archived': c.archived,
            'document_scope': c.document_scope, 'created_at': c.created_at,
            'updated_at': c.updated_at, **({'document_ids': [str(d) for d in documents]} if documents is not None else {})}

def message_out(m):
    return {'id': str(m.id), 'run_id': str(m.run_id), 'sequence': m.sequence,
            'role': m.role, 'content': m.content, 'status': m.status,
            'answer': m.answer, 'created_at': m.created_at}

def run_out(run, messages):
    return {'run_id': str(run.id), 'conversation_id': str(run.conversation_id),
            'client_message_id': str(run.client_message_id), 'status': run.status,
            'error_code': run.error_code, 'messages': [message_out(m) for m in messages]}

class ChatRepository:
    def __init__(self, session_factory, settings=None):
        self.sessions = session_factory
        self.settings = settings or get_chat_settings()

    async def _owner(self, s, owner):
        if (await lock_owner(s, owner)).is_deleted:
            raise ChatError('account_unavailable', 401)

    async def _conversation(self, s, owner, cid, *, lock=False):
        q = select(Conversation).where(Conversation.id == cid, Conversation.owner_id == owner)
        if lock: q = q.with_for_update()
        c = (await s.execute(q)).scalar_one_or_none()
        if c is None: raise ChatError('conversation_not_found', 404)
        return c

    async def _reap(self, s, cid):
        expired = (await s.scalars(select(GenerationRun).where(
            GenerationRun.conversation_id == cid, GenerationRun.status == 'running',
            GenerationRun.lease_until <= utcnow()).with_for_update())).all()
        for run in expired:
            await self._terminal(s, run, 'cancelled', 'generation_interrupted')

    async def _idle(self, s, cid):
        await self._reap(s, cid)
        if await s.scalar(select(GenerationRun.id).where(
                GenerationRun.conversation_id == cid, GenerationRun.status == 'running').limit(1)):
            raise ChatError('conversation_busy')

    async def _terminal(self, s, run, status, code):
        run.status, run.error_code, run.updated_at = status, code, utcnow()
        for message in (await s.scalars(select(ChatMessage).where(
                ChatMessage.run_id == run.id, ChatMessage.role == 'assistant'))).all():
            message.status = status
        await s.flush()

    async def create(self, owner, payload):
        async with self.sessions() as s, s.begin():
            await self._owner(s, owner)
            c = Conversation(owner_id=owner, title=payload.title, document_scope=payload.document_scope)
            s.add(c); await s.flush()
            return conversation_out(c, [])

    async def list(self, owner, limit, offset, archived=False):
        async with self.sessions() as s:
            rows = (await s.scalars(select(Conversation).where(Conversation.owner_id == owner,
                Conversation.archived == archived).order_by(Conversation.updated_at.desc(), Conversation.id.desc())
                .offset(offset).limit(limit + 1))).all()
            return {'items': [conversation_out(c) for c in rows[:limit]], 'has_more': len(rows) > limit}

    async def get(self, owner, cid):
        async with self.sessions() as s:
            c = await self._conversation(s, owner, cid)
            ids = (await s.scalars(select(ConversationDocument.document_id).where(
                ConversationDocument.conversation_id == cid))).all()
            return conversation_out(c, ids)

    async def update(self, owner, cid, payload):
        async with self.sessions() as s, s.begin():
            await self._owner(s, owner)
            c = await self._conversation(s, owner, cid, lock=True)
            await self._idle(s, cid)
            if payload.title is not None: c.title = payload.title
            if payload.archived is not None: c.archived = payload.archived
            c.updated_at = utcnow()
            return conversation_out(c)

    async def delete(self, owner, cid):
        async with self.sessions() as s, s.begin():
            await self._owner(s, owner)
            c = await self._conversation(s, owner, cid, lock=True)
            await s.delete(c)  # database FK cascades, including running turns

    async def select_documents(self, owner, cid, payload):
        if len(payload.document_ids) > self.settings.RAG_CHAT_MAX_DOCUMENTS:
            raise ChatError('too_many_documents', 422)
        if payload.document_scope == 'all_owner' and payload.document_ids:
            raise ChatError('all_owner_does_not_accept_document_ids', 422)
        async with self.sessions() as s, s.begin():
            await self._owner(s, owner)
            c = await self._conversation(s, owner, cid, lock=True)
            await self._idle(s, cid)
            found = (await s.scalars(select(Document.id).where(Document.id.in_(payload.document_ids),
                Document.owner_id == owner).with_for_update(read=True))).all()
            if len(found) != len(payload.document_ids):
                raise ChatError('document_not_found', 404)
            await s.execute(delete(ConversationDocument).where(ConversationDocument.conversation_id == cid))
            for doc_id in payload.document_ids:
                s.add(ConversationDocument(conversation_id=cid, document_id=doc_id))
            c.document_scope, c.updated_at = payload.document_scope, utcnow()
            return conversation_out(c, payload.document_ids)

    async def history(self, owner, cid, limit, before=None):
        async with self.sessions() as s, s.begin():
            # A reload also makes expired interrupted turns visible without new submission.
            await self._owner(s, owner)
            await self._conversation(s, owner, cid, lock=True)
            await self._reap(s, cid)
            q = select(ChatMessage).where(ChatMessage.conversation_id == cid)
            if before is not None: q = q.where(ChatMessage.sequence < before)
            rows = (await s.scalars(q.order_by(ChatMessage.sequence.desc()).limit(limit + 1))).all()
            page = list(reversed(rows[:limit]))
            return {'items': [message_out(m) for m in page], 'has_more': len(rows) > limit,
                    'next_before': page[0].sequence if page else None}

    async def begin(self, owner, cid, payload):
        digest = hashlib.sha256(json.dumps({'query': payload.query, 'top_k': payload.top_k},
                                          sort_keys=True).encode()).hexdigest()
        async with self.sessions() as s, s.begin():
            await self._owner(s, owner)
            c = await self._conversation(s, owner, cid, lock=True)
            await self._reap(s, cid)
            existing = (await s.scalars(select(GenerationRun).where(GenerationRun.conversation_id == cid,
                GenerationRun.client_message_id == payload.client_message_id))).one_or_none()
            if existing:
                if existing.payload_hash != digest: raise ChatError('idempotency_conflict')
                messages = (await s.scalars(select(ChatMessage).where(ChatMessage.run_id == existing.id)
                            .order_by(ChatMessage.sequence))).all()
                return {'replay': True, **run_out(existing, messages)}
            if c.archived: raise ChatError('conversation_archived')
            await self._idle(s, cid)
            old = (await s.scalars(select(ChatMessage).join(GenerationRun, ChatMessage.run_id == GenerationRun.id)
                .where(ChatMessage.conversation_id == cid, GenerationRun.status == 'completed')
                .order_by(ChatMessage.sequence.desc()).limit((self.settings.RAG_CHAT_HISTORY_MAX_MESSAGES // 2) * 2))).all()
            old = list(reversed(old))
            pairs = [(old[i].content, old[i+1].content) for i in range(0, len(old)-1, 2)
                     if old[i].role == 'user' and old[i+1].role == 'assistant']
            history = bounded_history(pairs, self.settings.RAG_CHAT_HISTORY_MAX_MESSAGES,
                                      self.settings.RAG_CHAT_HISTORY_MAX_BYTES)
            doc_ids = None if c.document_scope == 'all_owner' else list((await s.scalars(
                select(ConversationDocument.document_id).where(ConversationDocument.conversation_id == cid))).all())
            run = GenerationRun(conversation_id=cid, client_message_id=payload.client_message_id,
                payload_hash=digest, lease_until=utcnow()+timedelta(seconds=self.settings.RAG_CHAT_LEASE_SECONDS),
                document_ids=[str(d) for d in doc_ids] if doc_ids is not None else None)
            s.add(run); await s.flush()
            user = ChatMessage(conversation_id=cid, run_id=run.id, sequence=c.next_sequence,
                               role='user', content=payload.query, status='completed')
            assistant = ChatMessage(conversation_id=cid, run_id=run.id, sequence=c.next_sequence+1,
                                    role='assistant', content='', status='pending')
            s.add_all([user, assistant]); c.next_sequence += 2; c.updated_at = utcnow()
            if c.title == 'New chat': c.title = payload.query[:200]
            await s.flush()
            return {'replay': False, **run_out(run, [user, assistant]),
                    'history': history, 'document_ids': doc_ids}

    async def pulse(self, owner, cid, rid):
        async with self.sessions() as s, s.begin():
            await self._owner(s, owner)
            await self._conversation(s, owner, cid, lock=True)
            run = await s.get(GenerationRun, rid, with_for_update=True)
            if run is None or run.conversation_id != cid or run.status != 'running' or run.lease_until <= utcnow():
                raise GenerationError('generation_cancelled', 409)
            run.lease_until = utcnow()+timedelta(seconds=self.settings.RAG_CHAT_LEASE_SECONDS)
            run.updated_at = utcnow()

    async def finish(self, owner, cid, rid, answer):
        async with self.sessions() as s, s.begin():
            await self._owner(s, owner)
            c = await self._conversation(s, owner, cid, lock=True)
            run = await s.get(GenerationRun, rid, with_for_update=True)
            if run is None or run.conversation_id != cid or run.status != 'running' or run.lease_until <= utcnow():
                raise GenerationError('generation_cancelled', 409)
            source_ids = {uuid.UUID(source.document_id) for source in answer.sources}
            if run.document_ids is not None and not source_ids.issubset({uuid.UUID(d) for d in run.document_ids}):
                raise GenerationError("evidence_outside_scope", 409)
            found = (await s.scalars(select(Document.id).where(Document.id.in_(source_ids),
                Document.owner_id == owner, Document.status == 'ingested').with_for_update(read=True))).all()
            if len(found) != len(source_ids): raise GenerationError('evidence_unavailable', 409, True)
            messages = (await s.scalars(select(ChatMessage).where(ChatMessage.run_id == rid)
                         .order_by(ChatMessage.sequence))).all()
            assistant = next(m for m in messages if m.role == 'assistant')
            assistant.content, assistant.status = answer.answer, 'completed'
            assistant.answer = answer.model_dump(mode='json')
            run.status, run.updated_at, c.updated_at = 'completed', utcnow(), utcnow()
            await s.flush()
            return run_out(run, messages)

    async def fail(self, owner, cid, rid, status, code):
        async with self.sessions() as s, s.begin():
            await self._owner(s, owner)
            c = await self._conversation(s, owner, cid, lock=True)
            run = await s.get(GenerationRun, rid, with_for_update=True)
            if run is not None and run.conversation_id == cid and run.status == 'running':
                await self._terminal(s, run, status, code)
                c.updated_at = utcnow()

    async def run_status(self, owner, cid, rid):
        async with self.sessions() as s, s.begin():
            await self._owner(s, owner)
            await self._conversation(s, owner, cid, lock=True)
            await self._reap(s, cid)
            run = await s.get(GenerationRun, rid)
            if run is None or run.conversation_id != cid: raise ChatError('run_not_found', 404)
            messages = (await s.scalars(select(ChatMessage).where(ChatMessage.run_id == rid)
                                      .order_by(ChatMessage.sequence))).all()
            return run_out(run, messages)
