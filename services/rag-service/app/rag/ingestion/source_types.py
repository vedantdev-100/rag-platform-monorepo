"""
Maps an uploaded filename to the source_type stored on Document. Unknown
extensions map to "unknown", which the pipeline rejects up front (before
anything is written to disk or the database) rather than letting a parser
fail halfway through.
"""
from pathlib import Path

_SUFFIX_TO_SOURCE_TYPE = {
    ".pdf": "pdf",
    ".docx": "docx",
    ".pptx": "pptx",
    ".html": "html",
    ".htm": "html",
    ".md": "md",
    ".txt": "txt",
}


def detect_source_type(filename: str) -> str:
    return _SUFFIX_TO_SOURCE_TYPE.get(Path(filename).suffix.lower(), "unknown")
