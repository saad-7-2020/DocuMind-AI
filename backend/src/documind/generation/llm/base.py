from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

Message = dict[str, str]  # {"role": "system" | "user" | "assistant", "content": "..."}


@dataclass(frozen=True)
class LLMResult:
    content: str  # raw text; parsing and validation happen in the caller
    model: str
    input_tokens: int | None
    output_tokens: int | None
    latency_ms: int


class LLMProvider(Protocol):
    model_id: str

    def generate(self, messages: list[Message], schema_name: str, schema: dict) -> LLMResult: ...
