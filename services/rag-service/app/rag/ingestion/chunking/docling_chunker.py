"""
Docling's HybridChunker, wrapped behind this project's Chunker interface.

HybridChunker is structure-aware: it starts from the document's own
elements (paragraphs, list items, tables, pictures), splits any that
exceed the token budget, and (merge_peers) merges undersized neighbours
that share the same headings. What that gives retrieval:

* Every chunk's text is `contextualize()`d: the heading path is prepended,
  so the embedding AND the full-text index both see the section a passage
  belongs to (a query matching a section title can find its content).
* Tables are serialized with row/column labels ("Q2, Revenue = 120") and,
  when a table is too big for one chunk, split by rows with the header
  repeated, so every piece still says what its columns mean.
* Pictures contribute their caption and, when picture description is
  enabled, the generated description.

Chunk.modality marks the richest content type present in the chunk
("table" if it contains a table, else "image" if it contains a picture,
else "text"); the exact composition is in metadata["labels"].
"""
from docling.chunking import HybridChunker
from docling_core.transforms.chunker.tokenizer.base import BaseTokenizer

from app.exceptions import IngestionError
from app.rag.ingestion.base import Chunker, ChunkData, ParsedDocument


class DoclingHybridChunker(Chunker):
    def __init__(self, tokenizer: BaseTokenizer, merge_peers: bool = True):
        self._chunker = HybridChunker(tokenizer=tokenizer, merge_peers=merge_peers)

    def chunk(self, document: ParsedDocument) -> list[ChunkData]:
        if document.native is None:
            raise IngestionError(
                "DoclingHybridChunker needs the Docling document produced by DoclingParser; "
                "use RAG_CHUNKER_BACKEND=simple with other parsers"
            )

        chunks: list[ChunkData] = []
        for raw in self._chunker.chunk(dl_doc=document.native):
            text = self._chunker.contextualize(chunk=raw)
            if not text.strip():
                continue  # e.g. a picture with no caption and no description
            labels = sorted({str(getattr(i.label, "value", i.label)) for i in raw.meta.doc_items})
            pages = sorted({p.page_no for i in raw.meta.doc_items for p in (i.prov or [])})
            modality = "table" if "table" in labels else "image" if "picture" in labels else "text"
            chunks.append(ChunkData(
                content=text,
                modality=modality,
                metadata={
                    "headings": list(raw.meta.headings or []),
                    "labels": labels,
                    "pages": pages,
                },
            ))
        return chunks
