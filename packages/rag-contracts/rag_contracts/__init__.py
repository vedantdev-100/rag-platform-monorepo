"""Shared RAG data definitions, without database or inference dependencies."""
from rag_contracts.chunk import ChunkData
from rag_contracts.parsed_document import ParsedDocument, ParsedElement

__all__ = ["ChunkData", "ParsedDocument", "ParsedElement"]
from rag_contracts.ingestion_job import IngestionJob

__all__.append("IngestionJob")
