"""
Naive fixed-size chunker with character overlap — no layout/context
awareness, no Docling dependency. Exists as a swappable alternative (via
RAG_CHUNKER_BACKEND="simple") for cases where Docling's full pipeline is
overkill (plain unstructured text) or unavailable, and as a
network-independent option for local dev/CI. Uses RAG_CHUNK_SIZE/
RAG_CHUNK_OVERLAP from settings — the "dynamic, not hardcoded" values
already added when planning the retrieval layer.
"""
from app.core.config import get_settings
from app.rag.ingestion.base import Chunker, ChunkData, ParsedDocument

settings = get_settings()


class SimpleChunker(Chunker):
    def __init__(self, chunk_size: int | None = None, overlap: int | None = None):
        self.chunk_size = chunk_size or settings.RAG_CHUNK_SIZE
        self.overlap = overlap if overlap is not None else settings.RAG_CHUNK_OVERLAP

    def chunk(self, document: ParsedDocument) -> list[ChunkData]:
        full_text = "\n".join(e.text for e in document.elements)
        chunks: list[ChunkData] = []
        step = max(1, self.chunk_size - self.overlap)
        for start in range(0, len(full_text), step):
            piece = full_text[start:start + self.chunk_size]
            if piece.strip():
                chunks.append(ChunkData(content=piece, modality="text", metadata={}))
            if start + self.chunk_size >= len(full_text):
                break
        return chunks
