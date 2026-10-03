"""
Docling-based DocumentParser.

What it produces, and why it matters for retrieval:

* Tables are kept as tables. Each TableItem becomes a "table" element
  (markdown) in the flattened view, and Docling's HybridChunker serializes
  the same table with row/column labels ("Q2, Revenue = 120") so a value
  stays attached to its row and column headers when embedded.
* Pictures/charts have no text for a text embedding model to embed. When
  picture description is enabled (RAG_PICTURE_DESCRIPTION_ENABLED), Docling
  runs a vision-language model that attaches a text description to each
  picture; that description then becomes searchable chunk text. When it is
  off, pictures contribute only their caption (if any), and the parse
  statistics record how many pictures were NOT made searchable.
* Headings are tracked as a path (title -> section -> subsection) and
  travel with every element.

The rich DoclingDocument is returned in ParsedDocument.native so Docling's
own HybridChunker can chunk it; `elements` is a flattened, parser-agnostic
view for simpler chunkers.

Conversion is CPU-heavy and synchronous, so it runs in a worker thread —
never on the event loop, where it would stall every other request.

Verified offline in this project's tests: markdown, DOCX (tables, pictures,
headings), option construction. NOT verified in the build sandbox: the PDF
path (needs the layout/table/OCR models from `download_models`) and the
picture-description model itself (needs a VLM download).
"""
import asyncio
import tempfile
import threading
from pathlib import Path
from typing import Any

from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import (
    ConvertPipelineOptions,
    PdfPipelineOptions,
    PictureDescriptionApiOptions,
    PictureDescriptionVlmOptions,
)
from docling.document_converter import (
    DocumentConverter,
    PdfFormatOption,
    PowerpointFormatOption,
    WordFormatOption,
)
from docling.exceptions import ConversionError
from docling_core.types.doc.document import (
    DoclingDocument,
    PictureDescriptionData,
    PictureItem,
    SectionHeaderItem,
    TableItem,
    TextItem,
    TitleItem,
)

from app.core.config import Settings, get_settings
from app.exceptions import IngestionError, ModelNotFoundError
from app.logging import get_logger
from app.rag.ingestion.base import DocumentParser, ParsedDocument, ParsedElement
from app.rag.ingestion.model_paths import (
    DOWNLOAD_COMMAND,
    docling_models_dir,
    is_populated,
    repo_folder_name,
)

logger = get_logger(__name__)

# Docling has no plain-text input format; plain text is valid markdown, so
# .txt is parsed as .md. Caveat: markdown punctuation inside a .txt (a line
# starting with "#", "*" bullets, etc.) is interpreted as markdown.
_SUFFIX_ALIASES = {".txt": ".md", ".htm": ".html"}


# --------------------------------------------------------------------------
# Pipeline options (pure functions of Settings, so they are unit-testable)
# --------------------------------------------------------------------------

def _picture_description_options(settings: Settings):
    prompt = settings.RAG_PICTURE_DESCRIPTION_PROMPT
    if settings.RAG_PICTURE_DESCRIPTION_BACKEND == "api":
        headers: dict[str, str] = {}
        api_key = settings.RAG_PICTURE_DESCRIPTION_API_KEY.get_secret_value()
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        return PictureDescriptionApiOptions(
            url=settings.RAG_PICTURE_DESCRIPTION_API_URL,
            headers=headers,
            params={"model": settings.RAG_PICTURE_DESCRIPTION_API_MODEL},
            prompt=prompt,
            timeout=settings.RAG_PICTURE_DESCRIPTION_TIMEOUT,
            picture_area_threshold=settings.RAG_PICTURE_MIN_AREA,
        )
    return PictureDescriptionVlmOptions(
        repo_id=settings.RAG_PICTURE_DESCRIPTION_MODEL,
        prompt=prompt,
        picture_area_threshold=settings.RAG_PICTURE_MIN_AREA,
    )


def build_pipeline_options(settings: Settings) -> tuple[PdfPipelineOptions, ConvertPipelineOptions]:
    """Returns (options for PDF, options for DOCX/PPTX)."""
    local_models = settings.RAG_DOCLING_LOCAL_MODELS_ONLY
    description: dict[str, Any] = {}
    if settings.RAG_PICTURE_DESCRIPTION_ENABLED:
        description["do_picture_description"] = True
        description["picture_description_options"] = _picture_description_options(settings)
        # Only the "api" backend sends anything off this machine; make
        # Docling's remote-services opt-in explicit and tied to that choice.
        description["enable_remote_services"] = settings.RAG_PICTURE_DESCRIPTION_BACKEND == "api"

    # PDFs always need Docling's layout/table/OCR models, so they always
    # point at the local models folder.
    pdf_extra: dict[str, Any] = {"artifacts_path": docling_models_dir(settings)} if local_models else {}
    pdf_options = PdfPipelineOptions(
        do_ocr=settings.RAG_OCR_ENABLED,
        do_table_structure=settings.RAG_TABLE_STRUCTURE_ENABLED,
        # The description model needs the cropped picture images.
        generate_picture_images=settings.RAG_PICTURE_DESCRIPTION_ENABLED,
        **description,
        **pdf_extra,
    )

    # DOCX/PPTX need NO models unless a local picture-description VLM is on.
    # Docling validates artifacts_path eagerly (even when nothing would be
    # loaded from it), so setting it unnecessarily would make every DOCX
    # upload fail until models are downloaded. Only set it when needed.
    needs_models_for_simple_formats = (
        local_models
        and settings.RAG_PICTURE_DESCRIPTION_ENABLED
        and settings.RAG_PICTURE_DESCRIPTION_BACKEND == "local"
    )
    convert_extra: dict[str, Any] = (
        {"artifacts_path": docling_models_dir(settings)} if needs_models_for_simple_formats else {}
    )
    return pdf_options, ConvertPipelineOptions(**description, **convert_extra)


# --------------------------------------------------------------------------
# DoclingDocument -> flattened elements + statistics
# --------------------------------------------------------------------------

def _page_of(item) -> int | None:
    prov = getattr(item, "prov", None)
    return prov[0].page_no if prov else None


def _picture_description(item: PictureItem) -> str:
    for annotation in item.annotations:
        if isinstance(annotation, PictureDescriptionData) and annotation.text.strip():
            return annotation.text.strip()
    return ""


def flatten_docling_document(doc: DoclingDocument) -> tuple[list[ParsedElement], dict[str, Any]]:
    elements: list[ParsedElement] = []
    # Heading context is tracked as a depth-keyed stack, updated in document
    # order: a title resets it to depth 0, a section header at depth N drops
    # everything at depth >= N then pushes itself.
    heading_stack: list[tuple[int, str]] = []
    tables = pictures = pictures_described = 0

    # Table/picture captions are TextItems that also appear in reading order;
    # they're emitted with their table/picture, so skip the standalone copy.
    caption_refs = {c.cref for parent in (*doc.tables, *doc.pictures) for c in parent.captions}

    for item, _tree_level in doc.iterate_items():
        headings = [h[1] for h in heading_stack]

        if isinstance(item, TableItem):
            tables += 1
            caption = item.caption_text(doc).strip()
            markdown = item.export_to_markdown(doc=doc)
            text = f"{caption}\n{markdown}" if caption else markdown
            elements.append(ParsedElement(
                text=text,
                modality="table",
                headings=headings,
                metadata={
                    "label": "table",
                    "caption": caption,
                    "rows": getattr(item.data, "num_rows", None),
                    "cols": getattr(item.data, "num_cols", None),
                    "page": _page_of(item),
                },
            ))
        elif isinstance(item, PictureItem):
            pictures += 1
            caption = item.caption_text(doc).strip()
            description = _picture_description(item)
            if description:
                pictures_described += 1
            text = "\n".join(part for part in (caption, description) if part)
            if text:
                elements.append(ParsedElement(
                    text=text,
                    modality="image",
                    headings=headings,
                    metadata={
                        "label": "picture",
                        "caption": caption,
                        "description": description,
                        "page": _page_of(item),
                    },
                ))
        elif isinstance(item, TitleItem):
            heading_stack = [(0, item.text)]
        elif isinstance(item, SectionHeaderItem):
            depth = max(1, item.level or 1)
            heading_stack = [h for h in heading_stack if h[0] < depth]
            heading_stack.append((depth, item.text))
        elif isinstance(item, TextItem):
            if item.self_ref in caption_refs or not item.text.strip():
                continue
            elements.append(ParsedElement(
                text=item.text,
                modality="text",
                headings=headings,
                metadata={"label": str(getattr(item.label, "value", item.label)), "page": _page_of(item)},
            ))

    stats = {
        "pages": len(doc.pages),
        "tables": tables,
        "pictures": pictures,
        "pictures_described": pictures_described,
    }
    return elements, stats


# --------------------------------------------------------------------------
# Parser
# --------------------------------------------------------------------------

class DoclingParser(DocumentParser):
    supported_source_types = ("pdf", "docx", "pptx", "html", "md", "txt")

    def __init__(self, settings: Settings | None = None):
        self._settings = settings or get_settings()
        pdf_options, convert_options = build_pipeline_options(self._settings)
        self._converter = DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(pipeline_options=pdf_options),
                InputFormat.DOCX: WordFormatOption(pipeline_options=convert_options),
                InputFormat.PPTX: PowerpointFormatOption(pipeline_options=convert_options),
            }
        )
        # Bounds concurrent conversions (each is CPU/memory heavy).
        self._slots = threading.Semaphore(max(1, self._settings.RAG_PARSER_MAX_CONCURRENCY))

    async def parse(self, content: bytes, filename: str) -> ParsedDocument:
        suffix = Path(filename).suffix.lower()
        suffix = _SUFFIX_ALIASES.get(suffix, suffix)
        self._ensure_models_ready(suffix)

        doc = await asyncio.to_thread(self._convert_sync, content, suffix, filename)
        elements, stats = flatten_docling_document(doc)
        if stats["pictures"] > stats["pictures_described"]:
            logger.info(
                "pictures_not_searchable",
                filename=filename,
                pictures=stats["pictures"],
                described=stats["pictures_described"],
                hint="set RAG_PICTURE_DESCRIPTION_ENABLED=true to make picture content searchable",
            )
        return ParsedDocument(elements=elements, metadata=stats, native=doc)

    def _convert_sync(self, content: bytes, suffix: str, filename: str) -> DoclingDocument:
        with self._slots:
            # DocumentConverter needs a path, not bytes. delete=False plus an
            # explicit close() releases the file handle before Docling opens
            # the path — required on Windows, where an open temp file can't
            # be opened a second time.
            tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
            try:
                tmp.write(content)
                tmp.close()
                return self._converter.convert(tmp.name).document
            except ConversionError as exc:
                # Docling's message can contain the temp path; keep it in
                # the log and return a path-free message to the client.
                logger.warning("docling_conversion_failed", filename=filename, error=str(exc))
                raise IngestionError(
                    f"Could not parse {filename!r}: unreadable or unsupported {suffix} content"
                ) from exc
            finally:
                try:
                    Path(tmp.name).unlink(missing_ok=True)
                except OSError:
                    logger.warning("temp_file_cleanup_failed", path=tmp.name)

    def _ensure_models_ready(self, suffix: str) -> None:
        """Fail fast with a clear, actionable error instead of letting
        Docling die deep inside a model-loading stack trace."""
        settings = self._settings
        if not settings.RAG_DOCLING_LOCAL_MODELS_ONLY:
            return
        root = docling_models_dir(settings)

        if suffix == ".pdf" and not is_populated(root):
            logger.error("docling_models_missing", expected_path=str(root.resolve()))
            raise ModelNotFoundError(
                f"Docling layout models are not downloaded on the server. Run: {DOWNLOAD_COMMAND}"
            )

        wants_local_vlm = (
            settings.RAG_PICTURE_DESCRIPTION_ENABLED
            and settings.RAG_PICTURE_DESCRIPTION_BACKEND == "local"
            and suffix in (".pdf", ".docx", ".pptx")
        )
        if wants_local_vlm:
            vlm_dir = root / repo_folder_name(settings.RAG_PICTURE_DESCRIPTION_MODEL)
            if not is_populated(vlm_dir):
                logger.error("picture_model_missing", expected_path=str(vlm_dir.resolve()))
                raise ModelNotFoundError(
                    f"Picture-description model {settings.RAG_PICTURE_DESCRIPTION_MODEL!r} is not downloaded "
                    f"on the server. Run: {DOWNLOAD_COMMAND}"
                )
