"""Deterministic hashing embedder for tests and quick local tries.

Each (accent-stripped, lower-cased) word is hashed to a dimension and a sign, and the
vector is L2-normalized. Texts that share words get similar vectors, so retrieval
behaves sensibly for keyword-overlap questions, with no model download and no GPU.
It has no notion of meaning: "voiture" and "automobile" are unrelated to it.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections.abc import Sequence

import numpy as np

from documind.chunking.chunker import whitespace_token_count

_WORD = re.compile(r"\w+", re.UNICODE)


def _normalize(word: str) -> str:
    decomposed = unicodedata.normalize("NFKD", word.lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


class HashEmbedder:
    def __init__(self, dim: int = 1024) -> None:
        self.dim = dim
        self.model_id = f"fake/hash-{dim}"
        self.tokenizer_id = "whitespace"

    def _embed(self, text: str) -> np.ndarray:
        vec = np.zeros(self.dim, dtype=np.float32)
        for word in _WORD.findall(text):
            h = hashlib.blake2b(_normalize(word).encode(), digest_size=8).digest()
            idx = int.from_bytes(h[:4], "little") % self.dim
            vec[idx] += 1.0 if h[4] & 1 else -1.0
        norm = np.linalg.norm(vec)
        if norm == 0:
            vec[0] = 1.0  # avoid a zero vector (cosine undefined)
            return vec
        return vec / norm

    def embed_documents(self, texts: Sequence[str]) -> np.ndarray:
        return np.stack([self._embed(t) for t in texts]) if texts else np.zeros((0, self.dim), np.float32)

    def embed_query(self, text: str) -> np.ndarray:
        return self._embed(text)

    def count_tokens(self, text: str) -> int:
        return whitespace_token_count(text)
