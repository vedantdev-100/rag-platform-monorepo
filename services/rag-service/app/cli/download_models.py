"""
Downloads every model the RAG pipeline needs into MODELS_DIR (default:
./models in the project root). Run once per machine, with internet access:

    uv run python -m app.cli.download_models            # everything configured in .env
    uv run python -m app.cli.download_models --only embedding
    uv run python -m app.cli.download_models --only docling
    uv run python -m app.cli.download_models --check    # report what's missing, download nothing
    uv run python -m app.cli.download_models --force    # re-download

What gets downloaded depends on your .env (RAG_EMBEDDING_MODEL, tokenizer,
OCR / table-structure / picture-description switches), so you only fetch
what you'll actually use. After this, the service loads models from disk
and needs no internet access at runtime.

Files are written with huggingface_hub's `local_dir` mode: real files, no
symlinks — which sidesteps the Windows "A required privilege is not held by
the client" (WinError 1314) error the default HuggingFace cache can raise.
"""
import argparse
import json
import sys
from pathlib import Path

from huggingface_hub import snapshot_download

from app.core.config import Settings, get_settings
from app.rag.ingestion.model_paths import docling_models_dir, is_populated, local_model_path, repo_folder_name

MARKER_NAME = ".download_complete"
# A tokenizer-only download (when the chunker's tokenizer model differs from
# the embedding model) doesn't need the multi-hundred-MB weights.
TOKENIZER_FILES = ["tokenizer*", "vocab*", "merges.txt", "special_tokens_map.json", "added_tokens.json", "config.json", "*.model"]


def _marker_matches(target: Path, spec: dict) -> bool:
    marker = target / MARKER_NAME
    try:
        return json.loads(marker.read_text()) == spec
    except (OSError, ValueError):
        return False


def _write_marker(target: Path, spec: dict) -> None:
    (target / MARKER_NAME).write_text(json.dumps(spec))


def download_hf_repo(
    repo_id: str, target: Path, *, force: bool = False, allow_patterns: list[str] | None = None
) -> bool:
    """Returns True if it downloaded, False if it was already complete. The
    marker (written only after success) lets an interrupted download be
    resumed instead of being mistaken for a finished one."""
    spec = {"repo": repo_id, "patterns": allow_patterns}
    if not force and _marker_matches(target, spec):
        return False
    target.mkdir(parents=True, exist_ok=True)
    snapshot_download(
        repo_id=repo_id,
        local_dir=str(target),
        allow_patterns=allow_patterns,
        force_download=force,
    )
    _write_marker(target, spec)
    return True


def _download_docling_models(settings: Settings, force: bool) -> bool:
    # Imported lazily: pulls in torch/docling, which --check doesn't need.
    from docling.utils.model_downloader import download_models

    target = docling_models_dir(settings)
    spec = {
        "layout": True,
        "tableformer": settings.RAG_TABLE_STRUCTURE_ENABLED,
        "ocr": settings.RAG_OCR_ENABLED,
    }
    if not force and _marker_matches(target, spec):
        return False
    target.mkdir(parents=True, exist_ok=True)
    download_models(
        output_dir=target,
        force=force,
        progress=True,
        with_layout=True,
        with_tableformer=settings.RAG_TABLE_STRUCTURE_ENABLED,
        with_code_formula=False,  # code/formula enrichment isn't enabled in the pipeline
        with_picture_classifier=False,  # picture classification isn't enabled either
        with_rapidocr=settings.RAG_OCR_ENABLED,
        with_easyocr=False,
    )
    _write_marker(target, spec)
    return True

def _download_reranker_model(settings: Settings, force: bool) -> bool:
    repo = settings.RAG_RERANKER_MODEL
    return download_hf_repo(repo, local_model_path(repo, settings), force=force)

def _download_picture_model(settings: Settings, force: bool) -> bool:
    from docling.models.stages.picture_description.picture_description_vlm_model import (
        PictureDescriptionVlmModel,
    )

    repo = settings.RAG_PICTURE_DESCRIPTION_MODEL
    target = docling_models_dir(settings) / repo_folder_name(repo)
    spec = {"repo": repo}
    if not force and _marker_matches(target, spec):
        return False
    target.mkdir(parents=True, exist_ok=True)
    PictureDescriptionVlmModel.download_models(repo_id=repo, local_dir=target, force=force, progress=True)
    _write_marker(target, spec)
    return True


def missing_models(settings: Settings) -> list[str]:
    """Human-readable list of configured-but-absent models (empty = ready)."""
    missing: list[str] = []
    if settings.RAG_EMBEDDING_BACKEND == "sentence_transformers":
        if not is_populated(local_model_path(settings.RAG_EMBEDDING_MODEL, settings)):
            missing.append(f"embedding model {settings.RAG_EMBEDDING_MODEL}")
    if settings.RAG_CHUNKER_BACKEND == "docling" and settings.RAG_CHUNKER_TOKENIZER == "huggingface":
        if not is_populated(local_model_path(settings.RAG_CHUNKER_TOKENIZER_MODEL, settings)):
            missing.append(f"chunker tokenizer {settings.RAG_CHUNKER_TOKENIZER_MODEL}")
    if settings.RAG_PARSER_BACKEND == "docling" and settings.RAG_DOCLING_LOCAL_MODELS_ONLY:
        if not is_populated(docling_models_dir(settings)):
            missing.append("docling layout/table/OCR models")
        if settings.RAG_PICTURE_DESCRIPTION_ENABLED and settings.RAG_PICTURE_DESCRIPTION_BACKEND == "local":
            vlm_dir = docling_models_dir(settings) / repo_folder_name(settings.RAG_PICTURE_DESCRIPTION_MODEL)
            if not is_populated(vlm_dir):
                missing.append(f"picture-description model {settings.RAG_PICTURE_DESCRIPTION_MODEL}")
    if settings.RAG_RERANKER_ENABLED and settings.RAG_RERANKER_BACKEND == "local":
        if not is_populated(local_model_path(settings.RAG_RERANKER_MODEL, settings)):
            missing.append(f"reranker model {settings.RAG_RERANKER_MODEL}")
    return missing


def _run_step(label: str, action) -> bool:
    try:
        downloaded = action()
        print(f"[ok]   {label}" if downloaded else f"[skip] {label} (already downloaded; use --force to redo)")
        return True
    except Exception as exc:  # network errors, disk full, gated repos, ...
        print(f"[FAIL] {label}: {type(exc).__name__}: {exc}", file=sys.stderr)
        print("       Check your internet connection / HuggingFace access, then re-run.", file=sys.stderr)
        return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Download the models the RAG pipeline needs.")
    parser.add_argument("--only", choices=("all", "embedding", "docling"), default="all")
    parser.add_argument("--force", action="store_true", help="re-download even if already present")
    parser.add_argument("--check", action="store_true", help="only report missing models")
    args = parser.parse_args(argv)
    settings = get_settings()

    if args.check:
        missing = missing_models(settings)
        if missing:
            print("Missing models:\n  - " + "\n  - ".join(missing))
            print("Run: uv run python -m app.cli.download_models")
            return 1
        print("All configured models are present.")
        return 0

    ok = True
    if args.only in ("all", "embedding"):
        if settings.RAG_EMBEDDING_BACKEND == "sentence_transformers":
            ok &= _run_step(
                f"embedding model {settings.RAG_EMBEDDING_MODEL}",
                lambda: download_hf_repo(
                    settings.RAG_EMBEDDING_MODEL,
                    local_model_path(settings.RAG_EMBEDDING_MODEL, settings),
                    force=args.force,
                ),
            )
        needs_separate_tokenizer = (
            settings.RAG_CHUNKER_BACKEND == "docling"
            and settings.RAG_CHUNKER_TOKENIZER == "huggingface"
            and (
                settings.RAG_EMBEDDING_BACKEND != "sentence_transformers"
                or settings.RAG_CHUNKER_TOKENIZER_MODEL != settings.RAG_EMBEDDING_MODEL
            )
        )
        if needs_separate_tokenizer:
            ok &= _run_step(
                f"chunker tokenizer {settings.RAG_CHUNKER_TOKENIZER_MODEL}",
                lambda: download_hf_repo(
                    settings.RAG_CHUNKER_TOKENIZER_MODEL,
                    local_model_path(settings.RAG_CHUNKER_TOKENIZER_MODEL, settings),
                    force=args.force,
                    allow_patterns=TOKENIZER_FILES,
                ),
            )
        if settings.RAG_RERANKER_ENABLED and settings.RAG_RERANKER_BACKEND == "local":
            ok &= _run_step(
                f"reranker model {settings.RAG_RERANKER_MODEL}",
                lambda: _download_reranker_model(settings, args.force),
            )

    if args.only in ("all", "docling") and settings.RAG_PARSER_BACKEND == "docling":
        ok &= _run_step("docling layout/table/OCR models", lambda: _download_docling_models(settings, args.force))
        if settings.RAG_PICTURE_DESCRIPTION_ENABLED and settings.RAG_PICTURE_DESCRIPTION_BACKEND == "local":
            ok &= _run_step(
                f"picture-description model {settings.RAG_PICTURE_DESCRIPTION_MODEL}",
                lambda: _download_picture_model(settings, args.force),
            )

    still_missing = missing_models(settings)
    if still_missing:
        print("\nStill missing:\n  - " + "\n  - ".join(still_missing), file=sys.stderr)
    return 0 if ok and not still_missing else 1




if __name__ == "__main__":
    sys.exit(main())
