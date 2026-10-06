"""Backend-independent parsed content; native retained for local compatibility."""
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
