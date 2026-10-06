"""Ingestion interfaces; shared data definitions are re-exported for compatibility.

Existing parser, chunker and pipeline imports continue to work through this
module. Backend implementations remain local during this extraction step.
"""
from abc import ABC, abstractmethod

from rag_contracts import ChunkData, ParsedDocument, ParsedElement


class FileStorage(ABC):
    """Where raw uploaded bytes live. Documents/Chunks tables never store
    file content itself — only a URI this interface understands."""

    @abstractmethod
    async def save(self, content: bytes, filename: str) -> str:
        """Returns a URI (local path, S3 key, etc.) to store as Document.source_uri."""
        ...

    @abstractmethod
    async def read(self, uri: str) -> bytes:
        ...

    @abstractmethod
    async def delete(self, uri: str) -> None:
        ...


class DocumentParser(ABC):
    """Turns stored file bytes into layout-aware ParsedDocument. A parser
    declares which source_types it handles so the pipeline can pick the
    right one (or reject an unsupported upload) dynamically."""

    supported_source_types: tuple[str, ...] = ()

    @abstractmethod
    async def parse(self, content: bytes, filename: str) -> ParsedDocument:
        ...


class Chunker(ABC):
    @abstractmethod
    def chunk(self, document: ParsedDocument) -> list[ChunkData]:
        ...


class EmbeddingGenerator(ABC):
    @property
    @abstractmethod
    def dimensions(self) -> int:
        ...

    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        ...