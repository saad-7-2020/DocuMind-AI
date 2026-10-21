"""Grounded answer generation (§5.6–5.8).

The model returns structured JSON with an `answer_type`:
- "document": built only from the retrieved sources; every claim needs a verifiable citation, and an
  answer that ends up with no valid citation is turned into an abstention (the citation gate).
- "assistant" / "smalltalk": about the assistant itself or politeness: no sources needed.
- "insufficient": the sources can't answer: abstain, with a friendly explanation.

We also map S# → chunk/page, drop citations to sources that weren't in the context, and retry once
when the JSON is invalid. Phase 3 adds quote verification and the score-threshold gate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ValidationError

from documind.domain.errors import LLMBadOutput
from documind.domain.models import RetrievedChunk
from documind.generation.context import Source, render_sources, select_sources
from documind.generation.llm.base import LLMProvider, LLMResult, Message
from documind.generation.prompts import (
    ANSWER_SCHEMA,
    HISTORY_HEADER_FR,
    NO_SEARCH_FR,
    NO_SOURCES_FR,
    REPAIR_TEMPLATE_FR,
    USER_TEMPLATE_FR,
    Identity,
    build_system_prompt,
)

AnswerType = Literal["document", "assistant", "smalltalk", "insufficient"]
HISTORY_TURN_CHARS = 900


class LLMCitation(BaseModel):
    source_id: str
    quote: str


class LLMAnswer(BaseModel):
    answer_type: AnswerType = "document"
    answer: str | None = None
    citations: list[LLMCitation] = []
    insufficient_evidence: bool = False
    reason: str | None = None


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
    answer_type: str = "document"
    abstention_message: str | None = None  # the model's own friendly explanation, when it gave one
    citations_dropped: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    llm_latency_ms: int = 0
    llm_model: str | None = None
    llm_calls: int = 0
    notes: list[str] = field(default_factory=list)


class AnswerService:
    def __init__(self, llm: LLMProvider, context_max_chunks: int, context_max_tokens: int,
                 identity: Identity | None = None) -> None:
        self.llm = llm
        self.max_chunks = context_max_chunks
        self.max_tokens = context_max_tokens
        self.system_prompt = build_system_prompt(identity or Identity())

    def answer(self, question: str, chunks: list[RetrievedChunk],
               history: list[dict[str, str]] | None = None, searched: bool = True) -> GeneratedAnswer:
        sources = select_sources(chunks, self.max_chunks, self.max_tokens)
        no_sources = NO_SOURCES_FR if searched else NO_SEARCH_FR
        messages: list[Message] = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": USER_TEMPLATE_FR.format(
                sources=render_sources(sources) if sources else no_sources,
                history=_render_history(history), question=question)},
        ]
        out = GeneratedAnswer(None, False, None, [], sources)
        parsed = self._generate_validated(messages, out)
        out.answer_type = parsed.answer_type

        if parsed.answer_type == "insufficient" or parsed.insufficient_evidence:
            out.answer_type = "insufficient"
            out.abstained = True
            out.abstention_reason = "model_insufficient_evidence" if sources else "no_relevant_evidence"
            out.abstention_message = parsed.reason
            return out

        if parsed.answer_type in ("assistant", "smalltalk"):
            out.answer = parsed.answer  # about the assistant itself: nothing to cite
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
        if not out.citations:  # citation gate: a document answer nobody can verify is not an answer
            out.abstained = True
            out.abstention_reason = "no_valid_citations" if sources else "no_relevant_evidence"
            out.abstention_message = parsed.reason
            return out
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


def _render_history(history: list[dict[str, str]] | None) -> str:
    if not history:
        return ""
    turns = "\n".join(
        f"{'Utilisateur' if m['role'] == 'user' else 'Assistant'} : {m['content'][:HISTORY_TURN_CHARS]}"
        for m in history
    )
    return HISTORY_HEADER_FR.format(turns=turns)


def _short_error(e: ValidationError) -> str:
    return "; ".join(f"{'.'.join(map(str, err['loc'])) or 'root'}: {err['msg']}" for err in e.errors()[:5])
