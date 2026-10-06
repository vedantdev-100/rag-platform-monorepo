"""Core-only document projection shared by local and remote parsers."""
from typing import Any
from docling_core.types.doc.document import (
    DoclingDocument, PictureDescriptionData, PictureItem, SectionHeaderItem,
    TableItem, TextItem, TitleItem,
)
from app.rag.ingestion.base import ParsedElement

def _page_of(item) -> int | None:
    prov = getattr(item, "prov", None)
    return prov[0].page_no if prov else None


def _picture_description(item: PictureItem) -> str:
    description = getattr(getattr(item, "meta", None), "description", None)
    if description is not None and getattr(description, "text", "").strip():
        return description.text.strip()
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


