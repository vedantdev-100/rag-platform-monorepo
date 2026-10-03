"""
Resolves a HuggingFace repo id (e.g. "BAAI/bge-base-en-v1.5") to its local
folder under MODELS_DIR, and fails with an actionable error if it hasn't
been downloaded. Runtime code loads models from these folders only — it
never triggers a download itself. Downloading is an explicit, separate
step: `uv run python -m app.cli.download_models`.
"""
from pathlib import Path

from app.core.config import Settings, get_settings
from app.exceptions import ModelNotFoundError
from app.logging import get_logger

logger = get_logger(__name__)

DOWNLOAD_COMMAND = "uv run python -m app.cli.download_models"


def repo_folder_name(repo_id: str) -> str:
    # Same "org--name" convention HuggingFace's cache and Docling use, so
    # two orgs publishing a model with the same short name can't collide.
    return repo_id.replace("/", "--")


def local_model_path(repo_id: str, settings: Settings | None = None) -> Path:
    settings = settings or get_settings()
    return Path(settings.MODELS_DIR) / repo_folder_name(repo_id)


def docling_models_dir(settings: Settings | None = None) -> Path:
    settings = settings or get_settings()
    return Path(settings.MODELS_DIR) / "docling"


def is_populated(path: Path) -> bool:
    return path.is_dir() and any(path.iterdir())


def require_local_model(repo_id: str, settings: Settings | None = None) -> Path:
    path = local_model_path(repo_id, settings)
    if not is_populated(path):
        # Path goes to the log only; the exception message is returned to
        # API clients and must not disclose server filesystem layout.
        logger.error("model_not_downloaded", repo_id=repo_id, expected_path=str(path.resolve()))
        raise ModelNotFoundError(
            f"Required model {repo_id!r} is not downloaded on the server. Run: {DOWNLOAD_COMMAND}"
        )
    return path
