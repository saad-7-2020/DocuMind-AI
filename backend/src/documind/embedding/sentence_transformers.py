"""Local embedding with Sentence Transformers (default: BAAI/bge-m3, 1024-d).

Requires the `ml` extra (PyTorch). The model is loaded lazily on first use, so the
API process starts fast and tests never import torch.
"""

from __future__ import annotations

import threading
from collections.abc import Sequence
from typing import Any

import numpy as np
import structlog

log = structlog.get_logger(__name__)

# Some models need instruction prefixes; bge-m3 doesn't for dense retrieval.
_PREFIXES: dict[str, tuple[str, str]] = {
    "BAAI/bge-m3": ("", ""),
    "intfloat/multilingual-e5-base": ("query: ", "passage: "),
    "intfloat/multilingual-e5-small": ("query: ", "passage: "),
}

# Our chunks are ~350 tokens; capping the sequence length bounds GPU memory.
MAX_SEQ_LENGTH = 1024


class SentenceTransformerEmbedder:
    def __init__(self, model_id: str, dim: int, device: str = "auto", batch_size: int = 16,
                 cache_dir: str | None = None) -> None:
        self.model_id = model_id
        self.cache_dir = cache_dir
        self.dim = dim
        self.tokenizer_id = model_id
        self.batch_size = batch_size
        self._device_pref = device
        self._model: Any = None
        self._lock = threading.Lock()
        self._query_prefix, self._passage_prefix = _PREFIXES.get(model_id, ("", ""))

    @property
    def model(self) -> Any:
        if self._model is None:
            with self._lock:
                if self._model is None:
                    self._model = self._load()
        return self._model

    def _load(self) -> Any:
        import torch
        from sentence_transformers import SentenceTransformer

        device = self._device_pref
        if device == "auto":
            device = "cuda" if torch.cuda.is_available() else "cpu"
        # On GPU, load the weights directly in fp16: half the VRAM, faster on the GTX 1660 Super, and
        # (important on a machine with little free RAM) the fp32 copy is never materialized in memory.
        model_kwargs = {"dtype": torch.float16} if device == "cuda" else None
        model = SentenceTransformer(
            self.model_id, device=device, cache_folder=self.cache_dir, model_kwargs=model_kwargs
        )
        model.max_seq_length = MAX_SEQ_LENGTH
        get_dim = getattr(model, "get_embedding_dimension", None) or model.get_sentence_embedding_dimension
        actual = get_dim()
        if actual != self.dim:
            raise ValueError(f"{self.model_id} has dim {actual}, but EMBEDDING_DIM={self.dim}")
        log.info("embedder_loaded", model=self.model_id, device=device, dim=actual)
        return model

    def _encode(self, texts: list[str]) -> np.ndarray:
        vecs = self.model.encode(
            texts, batch_size=self.batch_size, normalize_embeddings=True, convert_to_numpy=True,
            show_progress_bar=False,
        )
        return vecs.astype(np.float32)

    def embed_documents(self, texts: Sequence[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), np.float32)
        return self._encode([self._passage_prefix + t for t in texts])

    def embed_query(self, text: str) -> np.ndarray:
        return self._encode([self._query_prefix + text])[0]

    def count_tokens(self, text: str) -> int:
        return len(self.model.tokenizer(text, add_special_tokens=False)["input_ids"])
