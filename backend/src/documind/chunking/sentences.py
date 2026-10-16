"""French-aware sentence splitting that returns character spans.

We need *spans* (start, end) rather than strings, so chunk offsets map exactly back
to the document text and therefore to page numbers. That's why this is a small
regex splitter with an abbreviation list instead of a library: offsets are exact
by construction, and the behavior is easy to test.
"""

from __future__ import annotations

import re

# Lower-cased abbreviations that end with a period but don't end a sentence.
FR_ABBREVIATIONS = {
    "m", "mm", "mme", "mmes", "mlle", "dr", "pr", "me", "st", "ste",
    "art", "al", "cf", "ex", "p", "pp", "env", "etc", "vol", "chap", "fig", "réf", "ref",
    "n", "no", "nº", "av", "bd", "j.-c", "c.-à-d", "i.e", "e.g", "min", "max", "tél", "tel",
    "janv", "févr", "fév", "avr", "juil", "sept", "oct", "nov", "déc",
}

# Candidate boundary: terminal punctuation, optional closing quotes/brackets (French puts a
# space before », as in « oui. »), then whitespace.
_BOUNDARY = re.compile(r"[.!?…]+(?:\s?[\"»”’)\]])*(?=\s+)")
_NEXT_STARTS_SENTENCE = re.compile(r"\s+[«\"“(\[]?\s*[A-ZÀ-ÖØ-Þ0-9]")
_WORD_BEFORE = re.compile(r"([\w.\-]+)$")  # stops at apostrophes: "l'art." → "art."


def sentence_spans(text: str, start: int = 0, end: int | None = None) -> list[tuple[int, int]]:
    """Split text[start:end] into sentence spans. Paragraph breaks always split."""
    end = len(text) if end is None else end
    spans: list[tuple[int, int]] = []
    for para_start, para_end in _paragraph_spans(text, start, end):
        spans.extend(_split_paragraph(text, para_start, para_end))
    return spans


def _paragraph_spans(text: str, start: int, end: int) -> list[tuple[int, int]]:
    spans = []
    pos = start
    for m in re.finditer(r"\n\s*\n", text[start:end]):
        s, e = start + m.start(), start + m.end()
        if text[pos:s].strip():
            spans.append(_trim(text, pos, s))
        pos = e
    if text[pos:end].strip():
        spans.append(_trim(text, pos, end))
    return spans


def _split_paragraph(text: str, start: int, end: int) -> list[tuple[int, int]]:
    spans = []
    sent_start = start
    segment = text[start:end]
    for m in _BOUNDARY.finditer(segment):
        boundary = start + m.end()
        if not _NEXT_STARTS_SENTENCE.match(text, boundary, end):
            continue
        punct = re.match(r"[.!?…]+", m.group(0)).group(0)  # type: ignore[union-attr]
        if punct == ".":
            before = _WORD_BEFORE.search(text, sent_start, start + m.start())
            if before and _is_abbreviation(before.group(1)):
                continue
        spans.append(_trim(text, sent_start, boundary))
        sent_start = boundary
    if text[sent_start:end].strip():
        spans.append(_trim(text, sent_start, end))
    return [s for s in spans if s[1] > s[0]]


def _is_abbreviation(word: str) -> bool:
    w = word.lower().rstrip(".")
    # Single letters are initials ("J. Dupont") or list markers ("a."): don't split.
    return w in FR_ABBREVIATIONS or len(w) == 1


def _trim(text: str, start: int, end: int) -> tuple[int, int]:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, end
