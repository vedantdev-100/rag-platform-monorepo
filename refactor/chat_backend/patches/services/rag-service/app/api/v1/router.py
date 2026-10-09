from fastapi import APIRouter

from app.api.v1.endpoints import documents, search

api_router = APIRouter()
api_router.include_router(documents.router)
api_router.include_router(search.router)

from app.api.v1.endpoints import generation, document_events
api_router.include_router(generation.router)
api_router.include_router(document_events.router)

from app.api.v1.endpoints import conversations
api_router.include_router(conversations.router)
