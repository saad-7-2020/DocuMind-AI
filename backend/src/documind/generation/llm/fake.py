"""Deterministic LLM stand-ins for tests and offline runs."""

from __future__ import annotations

import json
import re
from collections.abc import Callable

from documind.generation.llm.base import LLMResult, Message

_SOURCE = re.compile(r'<source id="(S\d+)"[^>]*>\n(.*?)\n</source>', re.S)


class ScriptedLLM:
    """Returns pre-written responses in order (or computes them with a function)."""

    def __init__(self, responses: list[str] | Callable[[list[Message]], str]) -> None:
        self.model_id = "fake/scripted"
        self._responses = responses
        self.calls: list[list[Message]] = []

    def generate(self, messages: list[Message], schema_name: str, schema: dict) -> LLMResult:
        self.calls.append(messages)
        if callable(self._responses):
            content = self._responses(messages)
        else:
            content = self._responses[min(len(self.calls), len(self._responses)) - 1]
        return LLMResult(content=content, model=self.model_id, input_tokens=100, output_tokens=20, latency_ms=1)


def echo_first_source(messages: list[Message]) -> str:
    """Answer with the first sentence of source S1, citing it. Good enough to test the
    plumbing end to end (IDs, pages, citations) without a real model."""
    m = _SOURCE.search(messages[-1]["content"])
    if not m:
        return json.dumps({"answer": None, "citations": [], "insufficient_evidence": True,
                           "reason": "no sources"})
    sid, text = m.group(1), m.group(2)
    quote = text.split(". ")[0][:200]
    return json.dumps({"answer": f"{quote} [{sid}]", "citations": [{"source_id": sid, "quote": quote}],
                       "insufficient_evidence": False, "reason": None})


class EchoLightLLM:
    """Stand-in for the small 'light' model: rewrites nothing, describes documents from their first words."""

    def __init__(self) -> None:
        self.model_id = "fake/light"
        self.calls: list[tuple[str, list[Message]]] = []

    def generate(self, messages: list[Message], schema_name: str, schema: dict) -> LLMResult:
        self.calls.append((schema_name, messages))
        user = messages[-1]["content"]
        if schema_name == "standalone_question":
            m = re.search(r"Dernière question : (.*)\Z", user, re.S)
            content = json.dumps({"standalone_question": (m.group(1) if m else user).strip()})
        elif schema_name == "document_description":
            text = re.sub(r"\s+", " ", user.split("Texte du document :", 1)[-1]).strip()
            words = text.split()
            content = json.dumps({
                "summary": " ".join(words[:30]) + ("…" if len(words) > 30 else ""),
                "keywords": [w.strip(".,;:()").lower() for w in words if len(w) > 6][:5],
                "suggested_questions": ["De quoi parle ce document ?", "Quels sont les points clés ?",
                                        "Quelles dates ou montants sont mentionnés ?"],
            })
        else:
            content = "{}"
        return LLMResult(content=content, model=self.model_id, input_tokens=50, output_tokens=20, latency_ms=1)
