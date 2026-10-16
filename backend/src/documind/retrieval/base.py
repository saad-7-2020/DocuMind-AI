from __future__ import annotations

from typing import Protocol

from documind.domain.models import RetrievedChunk, SearchFilters


class Retriever(Protocol):
    name: str

    def retrieve(self, question: str, filters: SearchFilters, k: int) -> list[RetrievedChunk]: ...
