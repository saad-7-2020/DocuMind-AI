"""Text cleaning applied to every page before chunking.

Retrieval can't find what extraction mangled. These are the cheap, safe fixes:
- Unicode NFKC: ligatures (ﬁ → fi), full-width forms, and the non-breaking spaces
  French typography puts before « : ; ! ? » all become plain characters.
- De-hyphenation of words split across lines ("informa-\\ntion" → "information").
- Whitespace normalization.
- Removal of running headers/footers and bare page numbers. They repeat on every
  page, so they pollute every chunk and inflate keyword matches.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import replace

from documind.domain.models import PageText

_HYPHEN_BREAK = re.compile(r"(\w)-\n(?=[a-zà-ÿ])")
_SPACES = re.compile(r"[ \t  ]+")
_MANY_NEWLINES = re.compile(r"\n{3,}")
_PAGE_NUMBER = re.compile(r"^\s*(page\s*)?[-–—]?\s*\d{1,4}\s*([/|]|sur|of)?\s*\d{0,4}\s*[-–—]?\s*$", re.I)
_DIGITS = re.compile(r"\d+")

HEADER_FOOTER_MIN_PAGES = 3
HEADER_FOOTER_RATIO = 0.6


def clean_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _HYPHEN_BREAK.sub(r"\1", text)
    lines = [_SPACES.sub(" ", line).strip() for line in text.split("\n")]
    text = "\n".join(lines)
    text = _MANY_NEWLINES.sub("\n\n", text)
    return text.strip()


def _signature(line: str) -> str:
    """Compare header/footer lines with page numbers masked out."""
    return _DIGITS.sub("#", line.lower())


def remove_headers_footers(pages: list[list[str]]) -> list[list[str]]:
    """Drop the first/last line of each page when it repeats on most pages, and bare page numbers."""
    def edge_lines(lines: list[str]) -> list[str]:
        non_empty = [line for line in lines if line]
        return list({non_empty[0], non_empty[-1]}) if non_empty else []

    repeated: set[str] = set()
    if len(pages) >= HEADER_FOOTER_MIN_PAGES:
        counts = Counter(_signature(line) for lines in pages for line in edge_lines(lines))
        threshold = HEADER_FOOTER_RATIO * len(pages)
        repeated = {sig for sig, n in counts.items() if n >= threshold}

    cleaned = []
    for lines in pages:
        non_empty_idx = [i for i, line in enumerate(lines) if line]
        edges = {non_empty_idx[0], non_empty_idx[-1]} if non_empty_idx else set()
        cleaned.append([
            line for i, line in enumerate(lines)
            if not (i in edges and (_signature(line) in repeated or _PAGE_NUMBER.match(line)))
        ])
    return cleaned


def clean_pages(pages: list[PageText]) -> list[PageText]:
    normalized = [clean_text(p.text).split("\n") for p in pages]
    stripped = remove_headers_footers(normalized)
    return [replace(p, text=clean_text("\n".join(lines))) for p, lines in zip(pages, stripped, strict=True)]
