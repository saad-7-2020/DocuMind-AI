"""Turn retrieved chunks into numbered sources for the prompt (§5.5)."""

from __future__ import annotations

from dataclasses import dataclass
from xml.sax.saxutils import escape, quoteattr

from documind.domain.models import RetrievedChunk


@dataclass(frozen=True)
class Source:
    source_id: str  # "S1", "S2", …: short labels the model can cite reliably
    chunk: RetrievedChunk


def select_sources(chunks: list[RetrievedChunk], max_chunks: int, max_tokens: int) -> list[Source]:
    """Keep the best chunks that fit the budget. The token budget uses the embedder's
    token counts, which is a close-enough proxy for the LLM's tokenizer."""
    sources: list[Source] = []
    seen: set = set()
    used = 0
    for chunk in chunks:
        if len(sources) >= max_chunks:
            break
        if chunk.chunk_id in seen:
            continue
        if sources and used + chunk.token_count > max_tokens:
            continue  # a smaller, lower-ranked chunk may still fit
        seen.add(chunk.chunk_id)
        used += chunk.token_count
        sources.append(Source(source_id=f"S{len(sources) + 1}", chunk=chunk))
    return sources


def render_sources(sources: list[Source]) -> str:
    """Wrap each chunk in a <source> tag. The text is escaped, so a document can't
    close the tag and smuggle in text that looks like instructions."""
    parts = []
    for s in sources:
        c = s.chunk
        pages = str(c.page_start) if c.page_start == c.page_end else f"{c.page_start}-{c.page_end}"
        parts.append(
            f"<source id={quoteattr(s.source_id)} document={quoteattr(c.filename)} pages={quoteattr(pages)}>\n"
            f"{escape(c.text)}\n</source>"
        )
    return "\n\n".join(parts)
