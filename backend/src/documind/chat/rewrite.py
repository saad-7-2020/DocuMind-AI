"""Turn a follow-up question into a standalone one, using the recent conversation.

"Et le prix ?" means nothing to a search engine; "Quel est le prix annuel de la maintenance du contrat ?"
does. This step uses a small, fast model. It never blocks a chat: on any failure the original question
is used as is.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import structlog

from documind.generation.llm.base import LLMProvider
from documind.generation.prompts import REWRITE_SCHEMA, REWRITE_SYSTEM_FR, REWRITE_USER_FR

log = structlog.get_logger(__name__)
TURN_CHARS = 500


@dataclass
class Rewrite:
    question: str  # what to search with
    rewritten: bool
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0


class QuestionRewriter:
    def __init__(self, llm: LLMProvider) -> None:
        self.llm = llm

    def rewrite(self, history: list[dict[str, str]], question: str) -> Rewrite:
        if not history:
            return Rewrite(question, False)
        turns = "\n".join(
            f"{'Utilisateur' if m['role'] == 'user' else 'Assistant'} : {m['content'][:TURN_CHARS]}" for m in history
        )
        try:
            result = self.llm.generate(
                [{"role": "system", "content": REWRITE_SYSTEM_FR},
                 {"role": "user", "content": REWRITE_USER_FR.format(turns=turns, question=question)}],
                "standalone_question", REWRITE_SCHEMA,
            )
            standalone = str(json.loads(result.content)["standalone_question"]).strip()
        except Exception as e:  # network, rate limit, malformed JSON: fall back, never fail the chat
            log.warning("rewrite_failed", error_type=type(e).__name__)
            return Rewrite(question, False)
        if not standalone or len(standalone) > 1000:
            return Rewrite(question, False)
        return Rewrite(standalone, standalone != question, result.input_tokens or 0, result.output_tokens or 0,
                       result.latency_ms)
