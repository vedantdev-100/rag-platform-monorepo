"""
Token counting for the chunker.

Chunk size only means something relative to the embedding model that will
read the chunk, so the default counts tokens with the REAL tokenizer of
RAG_CHUNKER_TOKENIZER_MODEL (same model as the embedder), loaded from the
local MODELS_DIR folder — no network. `approx` exists for tests and
offline experiments; chunk sizes are then only approximate.
"""
from docling_core.transforms.chunker.tokenizer.base import BaseTokenizer
from docling_core.transforms.chunker.tokenizer.huggingface import HuggingFaceTokenizer

from app.core.config import Settings, get_settings
from app.rag.ingestion.model_paths import require_local_model


class ApproxTokenizer(BaseTokenizer):
    """Word count x 1.3 (a rough subword-token estimate). No model needed."""

    max_tokens: int = 512

    def count_tokens(self, text: str) -> int:
        return max(1, int(len(text.split()) * 1.3))

    def get_max_tokens(self) -> int:
        return self.max_tokens

    def get_tokenizer(self):
        return None


def build_tokenizer(settings: Settings | None = None) -> BaseTokenizer:
    settings = settings or get_settings()
    if settings.RAG_CHUNKER_TOKENIZER == "approx":
        return ApproxTokenizer(max_tokens=settings.RAG_CHUNKER_MAX_TOKENS)
    path = require_local_model(settings.RAG_CHUNKER_TOKENIZER_MODEL, settings)
    return HuggingFaceTokenizer.from_pretrained(
        model_name=str(path), max_tokens=settings.RAG_CHUNKER_MAX_TOKENS
    )
