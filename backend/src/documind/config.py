"""Single source of configuration, read from environment variables / backend/.env."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Database
    database_url: str = "postgresql+psycopg://documind:documind@localhost:5433/documind"

    # Storage and upload limits
    storage_dir: Path = Path("./data/blobs")
    max_upload_bytes: int = 50 * 1024 * 1024
    max_pages: int = 1000

    # Embedding
    embedder: Literal["sentence_transformers", "fake"] = "sentence_transformers"
    embedding_model: str = "BAAI/bge-m3"
    embedding_dim: int = 1024
    model_device: Literal["auto", "cuda", "cpu"] = "auto"
    model_cache_dir: Path | None = None  # where Hugging Face models are downloaded (None = HF default)
    embed_batch_size: int = 16

    # Chunking
    chunk_max_tokens: int = 350
    chunk_overlap_tokens: int = 50

    # Retrieval and context
    retrieval_candidates: int = 50
    max_top_k: int = 20
    context_max_chunks: int = 6
    context_max_tokens: int = 3000

    # LLM
    llm_provider: Literal["openai_compat", "fake"] = "openai_compat"
    llm_base_url: str = "https://api.groq.com/openai/v1"
    groq_api_key: SecretStr = SecretStr("")
    llm_model: str = "openai/gpt-oss-120b"
    llm_structured_mode: Literal["json_schema", "json_object"] = "json_schema"
    llm_reasoning_effort: str | None = "low"
    llm_temperature: float = 0.0
    llm_max_output_tokens: int = 1500
    llm_timeout_s: float = 60.0
    llm_max_retries: int = Field(default=3, ge=1, le=5)

    # Question limits
    max_question_chars: int = 2000

    # Worker
    worker_poll_interval_s: float = 1.0
    job_timeout_s: int = 1800

    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
