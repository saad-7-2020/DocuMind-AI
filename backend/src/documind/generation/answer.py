"""Grounded answer generation (§5.6–5.8, Phase 2 subset).

Phase 2 does: structured JSON output, one repair retry, mapping S# → chunk/page,
dropping citations to sources that weren't in the context, and abstaining when the
model reports insufficient evidence or nothing was retrieved.
Phase 3 adds quote verification, the score-threshold gate and the citation gate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from pydantic import BaseModel, ValidationError

from documind.domain.errors import LLMBadOutput
from documind.domain.models import RetrievedChunk
from documind.generation.context import Source, render_sources, select_sources
from documind.generation.llm.base import LLMProvider, LLMResult, Message
from documind.generation.prompts import (
    ANSWER_SCHEMA,
    REPAIR_TEMPLATE_FR,
    SYSTEM_PROMPT_FR,
    USER_TEMPLATE_FR,
)


class LLMCitation(BaseModel):
    source_id: str
    quote: str


class LLMAnswer(BaseModel):
    answer: str | None
    citations: list[LLMCitation]
    insufficient_evidence: bool
    reason: str | None


@dataclass(frozen=True)
class Citation:
    marker: str
    chunk_id: UUID
    document_id: UUID
    filename: str
    page_start: int
    page_end: int
    quote: str
    score: float


@dataclass
class GeneratedAnswer:
    answer: str | None
    abstained: bool
    abstention_reason: str | None
    citations: list[Citation]
    sources: list[Source]
    citations_dropped: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    llm_latency_ms: int = 0
    llm_model: str | None = None
    llm_calls: int = 0
    notes: list[str] = field(default_factory=list)


class AnswerService:
    def __init__(self, llm: LLMProvider, context_max_chunks: int, context_max_tokens: int) -> None:
        self.llm = llm
        self.max_chunks = context_max_chunks
        self.max_tokens = context_max_tokens

    def answer(self, question: str, chunks: list[RetrievedChunk]) -> GeneratedAnswer:
        sources = select_sources(chunks, self.max_chunks, self.max_tokens)
        if not sources:
            return GeneratedAnswer(None, True, "no_relevant_evidence", [], [])

        messages: list[Message] = [
            {"role": "system", "content": SYSTEM_PROMPT_FR},
            {"role": "user", "content": USER_TEMPLATE_FR.format(sources=render_sources(sources), question=question)},
        ]
        out = GeneratedAnswer(None, False, None, [], sources)
        parsed = self._generate_validated(messages, out)

        if parsed.insufficient_evidence:
            out.abstained, out.abstention_reason = True, "model_insufficient_evidence"
            return out

        by_id = {s.source_id: s for s in sources}
        for c in parsed.citations:
            src = by_id.get(c.source_id.strip().strip("[]"))
            if src is None:  # the model cited a source it was never given: fabricated
                out.citations_dropped += 1
                continue
            ch = src.chunk
            out.citations.append(Citation(
                marker=src.source_id, chunk_id=ch.chunk_id, document_id=ch.document_id, filename=ch.filename,
                page_start=ch.page_start, page_end=ch.page_end, quote=c.quote, score=ch.score,
            ))
        out.answer = parsed.answer
        return out

    def _generate_validated(self, messages: list[Message], out: GeneratedAnswer) -> LLMAnswer:
        result = self._call(messages, out)
        try:
            return LLMAnswer.model_validate_json(result.content)
        except ValidationError as e:
            # One repair attempt: show the model its own output and the validation error.
            repair = messages + [
                {"role": "assistant", "content": result.content},
                {"role": "user", "content": REPAIR_TEMPLATE_FR.format(error=_short_error(e))},
            ]
            result = self._call(repair, out)
            try:
                return LLMAnswer.model_validate_json(result.content)
            except ValidationError as e2:
                raise LLMBadOutput("The model's answer did not match the expected format.") from e2

    def _call(self, messages: list[Message], out: GeneratedAnswer) -> LLMResult:
        result = self.llm.generate(messages, "grounded_answer", ANSWER_SCHEMA)
        out.llm_calls += 1
        out.llm_model = result.model
        out.input_tokens += result.input_tokens or 0
        out.output_tokens += result.output_tokens or 0
        out.llm_latency_ms += result.latency_ms
        return result


def _short_error(e: ValidationError) -> str:
    return "; ".join(f"{'.'.join(map(str, err['loc'])) or 'root'}: {err['msg']}" for err in e.errors()[:5])
