import uuid

import pytest

from documind.chunking.chunker import (
    ChunkerConfig,
    RecursiveChunker,
    chunk_id,
    join_pages,
    whitespace_token_count,
)
from documind.domain.models import ExtractionMethod, PageText


def pages(*texts: str) -> list[PageText]:
    return [PageText(i + 1, t, ExtractionMethod.PLAIN) for i, t in enumerate(texts)]


def make(max_tokens=20, overlap=5) -> RecursiveChunker:
    return RecursiveChunker(ChunkerConfig(max_tokens, overlap), whitespace_token_count, "whitespace")


def sentence(i: int) -> str:
    return f"Phrase numéro {i} décrit une clause importante du contrat."  # 8 words


LONG = " ".join(sentence(i) for i in range(30))


def test_chunks_are_exact_slices_of_document_text():
    p = pages(LONG[:400], LONG[400:])
    text, _ = join_pages(p)
    for c in make().chunk(p):
        assert text[c.char_start : c.char_end] == c.text


def test_token_budget_is_respected():
    chunks = make(max_tokens=20).chunk(pages(LONG))
    assert len(chunks) > 1
    assert all(c.token_count <= 20 for c in chunks)


def test_consecutive_chunks_overlap_and_cover_everything():
    # Sentences are 9 tokens, so an overlap budget of 10 carries one sentence over.
    chunks = make(max_tokens=30, overlap=10).chunk(pages(LONG))
    for a, b in zip(chunks, chunks[1:], strict=False):
        assert b.char_start < a.char_end, "expected overlap"
        assert b.char_start > a.char_start, "must always move forward"
        assert a.text.endswith(b.text[: b.text.index(".") + 1])  # the shared sentence
    assert chunks[0].char_start == 0 and chunks[-1].char_end == len(LONG)


def test_overlap_is_sentence_level():
    # Overlap never cuts a sentence: if the last sentence is bigger than the overlap
    # budget (9 > 8 tokens here), consecutive chunks simply don't overlap.
    chunks = make(max_tokens=20, overlap=8).chunk(pages(LONG))
    for a, b in zip(chunks, chunks[1:], strict=False):
        assert b.char_start >= a.char_end


def test_no_overlap_when_disabled():
    chunks = make(max_tokens=20, overlap=0).chunk(pages(LONG))
    for a, b in zip(chunks, chunks[1:], strict=False):
        assert b.char_start >= a.char_end


def test_page_numbers_follow_offsets():
    p = pages("Première page. Elle parle du prix.", "Deuxième page. Elle parle de la durée.",
              "Troisième page. Elle parle de la résiliation.")
    chunks = make(max_tokens=7, overlap=0).chunk(p)
    resil = next(c for c in chunks if "résiliation" in c.text)
    assert (resil.page_start, resil.page_end) == (3, 3)
    whole = make(max_tokens=100).chunk(p)
    assert len(whole) == 1 and (whole[0].page_start, whole[0].page_end) == (1, 3)


def test_overlong_sentence_is_split_at_words():
    text = " ".join(f"mot{i}" for i in range(55))  # one 55-token "sentence"
    chunks = make(max_tokens=20, overlap=0).chunk(pages(text))
    assert [c.token_count for c in chunks] == [20, 20, 15]


def test_giant_token_is_hard_cut():
    def chars_as_tokens(t: str) -> int:
        return len(t)

    chunker = RecursiveChunker(ChunkerConfig(50, 0), chars_as_tokens, "chars")
    chunks = chunker.chunk(pages("x" * 180))
    assert all(c.token_count <= 50 for c in chunks)
    assert "".join(c.text for c in chunks) == "x" * 180


def test_ids_are_deterministic_and_config_sensitive():
    doc = uuid.uuid4()
    a, b = make(20, 5), make(20, 5)
    assert a.config_hash == b.config_hash
    assert chunk_id(doc, a.config_hash, 3) == chunk_id(doc, b.config_hash, 3)
    assert make(30, 5).config_hash != a.config_hash


def test_invalid_overlap_rejected():
    with pytest.raises(ValueError):
        ChunkerConfig(max_tokens=10, overlap_tokens=10)
