from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from app.exceptions.base import AppError, InvalidCredentialsError, UserAlreadyExistsError, UserNotFoundError
from app.logging import get_logger

logger = get_logger(__name__)

_STATUS_MAP = {
    InvalidCredentialsError: status.HTTP_401_UNAUTHORIZED,
    UserAlreadyExistsError: status.HTTP_409_CONFLICT,
    UserNotFoundError: status.HTTP_404_NOT_FOUND,
}


def register_exception_handlers(app: FastAPI, *, is_production: bool) -> None:
    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError):
        status_code = _STATUS_MAP.get(type(exc), status.HTTP_400_BAD_REQUEST)
        headers = {"WWW-Authenticate": "Bearer"} if status_code == 401 else None
        return JSONResponse(status_code=status_code, content={"detail": exc.message}, headers=headers)

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        logger.error("unhandled_exception", error=str(exc), path=request.url.path)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "Internal server error"} if is_production else {"detail": str(exc)},
        )
