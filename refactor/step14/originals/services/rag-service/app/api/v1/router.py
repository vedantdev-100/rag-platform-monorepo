from fastapi import APIRouter

from app.api.v1.endpoints import documents, search

api_router = APIRouter()
api_router.include_router(documents.router)
api_router.include_router(search.router)
