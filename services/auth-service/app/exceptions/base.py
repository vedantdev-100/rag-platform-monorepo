"""auth-service's OWN exceptions only InvalidTokenError, TokenExpiredError,
and InsufficientPermissionsError now live in platform_auth and are
registered by setup_auth() in main.py, not here.
"""


class AppError(Exception):
    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


class InvalidCredentialsError(AppError):
    pass


class UserAlreadyExistsError(AppError):
    pass


class UserNotFoundError(AppError):
    pass
