"""Structure-aware, token-bounded chunking (docs/architecture.md §4.3).

Algorithm:
1. Join pages into one document text, remembering where each page starts.
2. Split into *units*: sentences (paragraph breaks always split). A sentence longer
   than the budget is split at word boundaries.
3. Pack consecutive units greedily up to `max_tokens`.
4. Start the next chunk a few units back, so consecutive chunks share about
   `overlap_tokens` of text. A fact that straddles a boundary then appears whole
   in at least one chunk.

Every chunk is an exact slice `text[char_start:char_end]` of the document text, so
page numbers (and later, highlighted citations) are derived from offsets, not guessed.
"""

from __future__ import annotations

import bisect
import hashlib
import json
import re
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass

from documind.chunking.sentences import sentence_spans
from documind.domain.models import ChunkDraft, PageText

PAGE_SEPARATOR = "\n\n"
_CHUNK_NAMESPACE = uuid.UUID("6f1c3a52-6b8e-4d0e-9d6a-2f8f8d1c0a11")

TokenCounter = Callable[[str], int]


@dataclass(frozen=True)
class ChunkerConfig:
    max_tokens: int = 350
    overlap_tokens: int = 50
    version: str = "recursive-v1"

    def __post_init__(self) -> None:
        if not 0 <= self.overlap_tokens < self.max_tokens:
            raise ValueError("overlap_tokens must be >= 0 and < max_tokens")


@dataclass(frozen=True)
class _Unit:
    start: int
    end: int
    tokens: int


def join_pages(pages: list[PageText]) -> tuple[str, list[int]]:
    """Concatenate page texts; return the text and each page's start offset."""
    offsets, parts, pos = [], [], 0
    for i, page in enumerate(pages):
        if i:
            parts.append(PAGE_SEPARATOR)
            pos += len(PAGE_SEPARATOR)
        offsets.append(pos)
        parts.append(page.text)
        pos += len(page.text)
    return "".join(parts), offsets


def chunk_id(document_id: uuid.UUID, config_hash: str, chunk_index: int) -> uuid.UUID:
    """Deterministic: re-indexing with the same config yields the same IDs."""
    return uuid.uuid5(_CHUNK_NAMESPACE, f"{document_id}:{config_hash}:{chunk_index}")


class RecursiveChunker:
    def __init__(self, config: ChunkerConfig, count_tokens: TokenCounter, tokenizer_id: str) -> None:
        self.config = config
        self.count_tokens = count_tokens
        payload = json.dumps({**asdict(config), "tokenizer": tokenizer_id}, sort_keys=True)
        self.config_hash = hashlib.sha256(payload.encode()).hexdigest()[:16]

    def chunk(self, pages: list[PageText]) -> list[ChunkDraft]:
        text, page_offsets = join_pages(pages)
        units = self._units(text)
        drafts: list[ChunkDraft] = []
        for index, (first, last) in enumerate(self._pack(units)):
            start, end = units[first].start, units[last].end
            body = text[start:end]
            drafts.append(
                ChunkDraft(
                    chunk_index=index,
                    text=body,
                    char_start=start,
                    char_end=end,
                    page_start=pages[_page_index(page_offsets, start)].page_number,
                    page_end=pages[_page_index(page_offsets, end - 1)].page_number,
                    token_count=self.count_tokens(body),
                )
            )
        return drafts

    def _units(self, text: str) -> list[_Unit]:
        units: list[_Unit] = []
        for start, end in sentence_spans(text):
            n = self.count_tokens(text[start:end])
            if n <= self.config.max_tokens:
                units.append(_Unit(start, end, n))
            else:
                units.extend(self._split_long(text, start, end))
        return units

    def _split_long(self, text: str, start: int, end: int) -> list[_Unit]:
        """Split an over-long sentence at word boundaries (or hard-cut a giant 'word')."""
        units: list[_Unit] = []
        cur_start, cur_end, cur_tokens = None, start, 0
        for m in re.finditer(r"\S+", text[start:end]):
            w_start, w_end = start + m.start(), start + m.end()
            n = self.count_tokens(m.group(0))
            if n > self.config.max_tokens:  # pathological token soup: cut by characters
                if cur_start is not None:
                    units.append(_Unit(cur_start, cur_end, cur_tokens))
                    cur_start, cur_tokens = None, 0
                step = max(1, (w_end - w_start) * self.config.max_tokens // n)
                for s in range(w_start, w_end, step):
                    e = min(s + step, w_end)
                    units.append(_Unit(s, e, self.count_tokens(text[s:e])))
                continue
            if cur_start is not None and cur_tokens + n > self.config.max_tokens:
                units.append(_Unit(cur_start, cur_end, cur_tokens))
                cur_start, cur_tokens = None, 0
            if cur_start is None:
                cur_start = w_start
            cur_end, cur_tokens = w_end, cur_tokens + n
        if cur_start is not None:
            units.append(_Unit(cur_start, cur_end, cur_tokens))
        return units

    def _pack(self, units: list[_Unit]) -> list[tuple[int, int]]:
        """Greedy packing with unit-level overlap. Returns (first, last) unit indices."""
        groups: list[tuple[int, int]] = []
        i = 0
        while i < len(units):
            j, tokens = i, 0
            while j < len(units) and (j == i or tokens + units[j].tokens <= self.config.max_tokens):
                tokens += units[j].tokens
                j += 1
            groups.append((i, j - 1))
            if j >= len(units):
                break
            # Step back over trailing units that fit in the overlap budget (always move forward).
            k, overlap = j, 0
            while k - 1 > i and overlap + units[k - 1].tokens <= self.config.overlap_tokens:
                k -= 1
                overlap += units[k].tokens
            i = k
        return groups


def _page_index(page_offsets: list[int], char_pos: int) -> int:
    return bisect.bisect_right(page_offsets, char_pos) - 1


def whitespace_token_count(text: str) -> int:
    """Stand-in tokenizer for tests and the fake embedder: one token per word."""
    return len(text.split())
