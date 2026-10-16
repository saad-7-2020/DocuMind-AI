"""Text extraction, one `PageText` per page.

PDF: PyMuPDF text layer (OCR for image-only pages arrives in Phase 3).
TXT: decoded with charset detection, then split into logical pages so citations
can point somewhere more precise than "the whole file".
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Protocol

import pymupdf
from charset_normalizer import from_path

from documind.domain.errors import ExtractionError, NoTextFound, PdfEncrypted, TooManyPages
from documind.domain.models import MIME_PDF, MIME_TXT, ExtractionMethod, PageText

TXT_PAGE_CHARS = 3000


class Extractor(Protocol):
    def supports(self, mime: str) -> bool: ...
    def extract(self, path: Path) -> list[PageText]: ...


class PdfExtractor:
    def __init__(self, max_pages: int) -> None:
        self.max_pages = max_pages

    def supports(self, mime: str) -> bool:
        return mime == MIME_PDF

    def extract(self, path: Path) -> list[PageText]:
        try:
            doc = pymupdf.open(path, filetype="pdf")
        except Exception as e:  # malformed file
            raise ExtractionError("PDF could not be opened.") from e
        with doc:
            if doc.needs_pass:
                raise PdfEncrypted()
            if doc.page_count > self.max_pages:
                raise TooManyPages(f"{doc.page_count} pages; limit is {self.max_pages}.")
            pages = [
                PageText(page_number=i + 1, text=page.get_text("text", sort=True), method=ExtractionMethod.TEXT_LAYER)
                for i, page in enumerate(doc)
            ]
        if not any(p.text.strip() for p in pages):
            raise NoTextFound()
        return pages


class TxtExtractor:
    def supports(self, mime: str) -> bool:
        return mime == MIME_TXT

    def extract(self, path: Path) -> list[PageText]:
        best = from_path(path).best()
        if best is None:
            raise ExtractionError("Text encoding could not be detected.")
        text = str(best).replace("\r\n", "\n").replace("\r", "\n")
        if not text.strip():
            raise NoTextFound()
        return [
            PageText(page_number=i + 1, text=t, method=ExtractionMethod.PLAIN)
            for i, t in enumerate(split_logical_pages(text))
        ]


def split_logical_pages(text: str, target_chars: int = TXT_PAGE_CHARS) -> list[str]:
    """Split on form feeds if present, else pack paragraphs into ~target_chars pages."""
    if "\f" in text:
        return [p for p in text.split("\f") if p.strip()] or [text]
    paragraphs = re.split(r"(\n\s*\n)", text)  # keep separators so no text is lost
    pages: list[str] = []
    current = ""
    for part in paragraphs:
        if current and len(current) + len(part) > target_chars and part.strip():
            pages.append(current)
            current = ""
        current += part
    if current.strip():
        pages.append(current)
    return pages


def extractor_for(mime: str, extractors: list[Extractor]) -> Extractor:
    for ex in extractors:
        if ex.supports(mime):
            return ex
    raise ExtractionError(f"No extractor for {mime}.")
