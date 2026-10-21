"""Decide, for each message, whether the documents are needed at all (RAG used as a tool, only when useful).

"Bonjour", "merci", "qui t'a créé ?" or "plus court, s'il te plaît" must not trigger a document search:
the assistant answers them with its own personality. A question about the documents is searched, after
being turned into a standalone question ("et le prix ?" becomes a full question). This step uses the
small, fast model. It never blocks a chat: on any failure, the safe path is taken (search the documents).
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import structlog

from documind.generation.llm.base import LLMProvider
from documind.generation.prompts import ROUTE_SCHEMA, ROUTE_SYSTEM_FR, ROUTE_USER_FR, ROUTE_USER_NO_HISTORY_FR

log = structlog.get_logger(__name__)
TURN_CHARS = 500


@dataclass
class Route:
    needs_documents: bool
    question: str  # what to search with (the original message when no rewriting was needed)
    rewritten: bool = False
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0


class QuestionRouter:
    def __init__(self, llm: LLMProvider) -> None:
        self.llm = llm

    def route(self, history: list[dict[str, str]], question: str) -> Route:
        if history:
            turns = "\n".join(
                f"{'Utilisateur' if m['role'] == 'user' else 'Assistant'} : {m['content'][:TURN_CHARS]}"
                for m in history
            )
            user = ROUTE_USER_FR.format(turns=turns, question=question)
        else:
            user = ROUTE_USER_NO_HISTORY_FR.format(question=question)
        try:
            result = self.llm.generate(
                [{"role": "system", "content": ROUTE_SYSTEM_FR}, {"role": "user", "content": user}],
                "route_message", ROUTE_SCHEMA,
            )
            data = json.loads(result.content)
            needs = bool(data["needs_documents"])
            standalone = " ".join(str(data.get("standalone_question") or "").split())  # also folds NBSP
        except Exception as e:  # network, rate limit, malformed JSON: fall back, never fail the chat
            log.warning("route_failed", error_type=type(e).__name__)
            return Route(True, question)
        tokens = (result.input_tokens or 0, result.output_tokens or 0, result.latency_ms)
        if not needs:
            return Route(False, question, False, *tokens)
        if not standalone or len(standalone) > 1000:
            return Route(True, question, False, *tokens)
        return Route(True, standalone, standalone != " ".join(question.split()), *tokens)
