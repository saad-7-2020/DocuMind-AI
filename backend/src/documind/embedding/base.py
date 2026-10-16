from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

import numpy as np


class Embedder(Protocol):
    """Bi-encoder: queries and passages are embedded independently.

    Two methods, because many models expect different prefixes for queries and
    passages; mixing them up silently costs recall. Vectors are L2-normalized,
    so cosine similarity == dot product.
    """

    model_id: str
    dim: int
    tokenizer_id: str

    def embed_documents(self, texts: Sequence[str]) -> np.ndarray: ...  # (n, dim) float32
    def embed_query(self, text: str) -> np.ndarray: ...  # (dim,) float32
    def count_tokens(self, text: str) -> int: ...
