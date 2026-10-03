"""
Every service that depends on this package gets the same exception
types and the same HTTP mapping for them  one place to fix a status
code, not N places.
"""
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse


class AppError(Exception):
    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


class InvalidTokenError(AppError):
    pass


class TokenExpiredError(AppError):
    pass


class InsufficientPermissionsError(AppError):
    pass


_STATUS_MAP = {
    InvalidTokenError: status.HTTP_401_UNAUTHORIZED,
    TokenExpiredError: status.HTTP_401_UNAUTHORIZED,
    InsufficientPermissionsError: status.HTTP_403_FORBIDDEN,
}


def register_auth_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _handler(request: Request, exc: AppError):
        code = _STATUS_MAP.get(type(exc), status.HTTP_400_BAD_REQUEST)
        headers = {"WWW-Authenticate": "Bearer"} if code == 401 else None
        return JSONResponse(status_code=code, content={"detail": exc.message}, headers=headers)
