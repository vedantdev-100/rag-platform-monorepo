"""rag-service's OWN exceptions only shared ones live in platform_auth."""


class AppError(Exception):
    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


class GuardrailViolationError(AppError):
    pass


class RetrievalError(AppError):
    pass


class IngestionError(AppError):
    pass


class ModelNotFoundError(AppError):
    pass


class FileTooLargeError(AppError):
    pass
