"""
Ingestion-layer interfaces, mirroring the Retriever/Reranker pattern in
app/rag/retrieval/base.py: define the contract once, swap backends behind
it. Four stages, each independently swappable:

  raw file -> [FileStorage] -> stored URI
  stored file -> [DocumentParser] -> ParsedDocument (layout-aware elements)
  ParsedDocument -> [Chunker] -> list[ChunkData]
  ChunkData.content -> [EmbeddingGenerator] -> vector

IngestionPipeline (pipeline.py) wires these four together; nothing outside
this module needs to know which concrete backend is in use.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ParsedElement:
    """One layout-aware unit from a parsed document — a paragraph, a table,
    a heading, an image caption. Modality distinguishes how it should be
    chunked/embedded later."""
    text: str
    modality: str = "text"  # "text" | "table" | "image" | "audio" | "video"
    headings: list[str] = field(default_factory=list)  # section path, e.g. ["Ch 1", "1.2 Setup"]
    metadata: dict[str, Any] = field(default_factory=dict)  # page number, bbox, etc.


@dataclass
class ParsedDocument:
    # Flattened, backend-agnostic view (tables as markdown, pictures as
    # caption/description text). Enough for any simple Chunker.
    elements: list[ParsedElement]
    # Parse statistics: pages, tables, pictures, pictures_described, ...
    metadata: dict[str, Any] = field(default_factory=dict)
    # The parser's own rich document object (a DoclingDocument for
    # DoclingParser). Structure-aware chunkers (Docling's HybridChunker)
    # need it — it carries the heading tree, table cells, and picture
    # annotations that `elements` flattens away. None for parsers that
    # have no richer representation.
    native: Any = None


@dataclass
class ChunkData:
    """Output of chunking — what ChunkRepository.bulk_create() persists,
    minus document_id/chunk_index/embedding (the pipeline fills those in)."""
    content: str
    modality: str = "text"
    metadata: dict[str, Any] = field(default_factory=dict)


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
