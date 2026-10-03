from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from app.exceptions.base import (
    AppError, FileTooLargeError, GuardrailViolationError, IngestionError,
    ModelNotFoundError, RetrievalError,
)
from app.logging import get_logger

logger = get_logger(__name__)

_STATUS_MAP = {
    GuardrailViolationError: status.HTTP_422_UNPROCESSABLE_ENTITY,
    RetrievalError: status.HTTP_502_BAD_GATEWAY,
    IngestionError: status.HTTP_422_UNPROCESSABLE_ENTITY,
    FileTooLargeError: status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
    ModelNotFoundError: status.HTTP_503_SERVICE_UNAVAILABLE,
}


def register_exception_handlers(app: FastAPI, *, is_production: bool) -> None:
    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError):
        status_code = _STATUS_MAP.get(type(exc), status.HTTP_400_BAD_REQUEST)
        return JSONResponse(status_code=status_code, content={"detail": exc.message})

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        logger.error("unhandled_exception", error=str(exc), path=request.url.path)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "Internal server error"} if is_production else {"detail": str(exc)},
        )
