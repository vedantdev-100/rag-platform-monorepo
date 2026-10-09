from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, field_validator
from app.rag.retrieval.validation import normalize_query

class CreateConversation(BaseModel):
    model_config = ConfigDict(extra='forbid')
    title: str = Field('New chat', min_length=1, max_length=200)
    document_scope: Literal['selected', 'all_owner'] = 'selected'
    @field_validator('title')
    @classmethod
    def title_nonblank(cls, value):
        if not value.strip(): raise ValueError('Title cannot be blank')
        return value.strip()

class UpdateConversation(BaseModel):
    model_config = ConfigDict(extra='forbid')
    title: str | None = Field(None, min_length=1, max_length=200)
    archived: bool | None = None
    @field_validator('title')
    @classmethod
    def title_nonblank(cls, value):
        if value is not None and not value.strip(): raise ValueError('Title cannot be blank')
        return value.strip() if value is not None else value

class SelectDocuments(BaseModel):
    model_config = ConfigDict(extra='forbid')
    document_scope: Literal['selected', 'all_owner'] = 'selected'
    document_ids: list[UUID] = Field(default_factory=list, max_length=500)
    @field_validator('document_ids')
    @classmethod
    def unique_ids(cls, value):
        if len(set(value)) != len(value): raise ValueError('Duplicate document IDs')
        return value

class ChatTurn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    query: str = Field(min_length=1, max_length=2000)
    top_k: int | None = Field(None, ge=1, le=50, strict=True)
    client_message_id: UUID
    @field_validator('query')
    @classmethod
    def valid_query(cls, value):
        return normalize_query(value)

from datetime import datetime
from app.rag.generation.types import Answer

class ConversationOut(BaseModel):
    id: UUID
    title: str
    archived: bool
    document_scope: Literal['selected','all_owner']
    document_ids: list[UUID] | None = None
    created_at: datetime
    updated_at: datetime

class ConversationPage(BaseModel):
    items: list[ConversationOut]
    has_more: bool

class MessageOut(BaseModel):
    id: UUID
    run_id: UUID
    sequence: int
    role: Literal['user','assistant']
    content: str
    status: Literal['pending','completed','failed','cancelled']
    answer: Answer | None
    created_at: datetime

class MessagePage(BaseModel):
    items: list[MessageOut]
    has_more: bool
    next_before: int | None

class RunOut(BaseModel):
    run_id: UUID
    conversation_id: UUID
    client_message_id: UUID
    status: Literal['running','completed','failed','cancelled']
    error_code: str | None = None
    messages: list[MessageOut]
    replay: bool = False
