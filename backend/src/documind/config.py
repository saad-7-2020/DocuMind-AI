"""Single source of configuration, read from environment variables / backend/.env."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import AliasChoices, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", populate_by_name=True
    )

    # Database
    database_url: str = "postgresql+psycopg://documind:documind@127.0.0.1:5433/documind"

    # Storage and upload limits
    storage_backend: Literal["local", "supabase"] = "local"
    storage_dir: Path = Path("./data/blobs")  # blobs (local backend) and the upload spool directory
    max_upload_bytes: int = 50 * 1024 * 1024
    max_pages: int = 1000
    supabase_url: str = ""  # https://<project-ref>.supabase.co
    # Server-side secret: bypasses Storage access rules, never goes to the browser. The dashboard calls
    # it SUPABASE_SECRET_KEY (new `sb_secret_…` keys); the older name SUPABASE_SERVICE_KEY still works.
    supabase_secret_key: SecretStr = Field(
        default=SecretStr(""), validation_alias=AliasChoices("SUPABASE_SECRET_KEY", "SUPABASE_SERVICE_KEY")
    )
    supabase_bucket: str = "documents"  # must be a PRIVATE bucket

    # Embedding
    embedder: Literal["sentence_transformers", "openai_compat", "fake"] = "sentence_transformers"
    embedding_model: str = "BAAI/bge-m3"
    embedding_dim: int = 1024
    model_device: Literal["auto", "cuda", "cpu"] = "auto"
    model_cache_dir: Path | None = None  # where Hugging Face models are downloaded (None = HF default)
    embed_batch_size: int = 16
    # Hosted embeddings (EMBEDDER=openai_compat): any OpenAI-compatible /embeddings endpoint.
    embedding_base_url: str = "https://api.jina.ai/v1"
    embedding_api_key: SecretStr = SecretStr("")
    embedding_query_extra: dict[str, Any] = {}  # extra JSON body fields for questions, e.g. {"task": "retrieval.query"}
    embedding_document_extra: dict[str, Any] = {}  # ... for document chunks, e.g. {"task": "retrieval.passage"}
    embedding_send_dimensions: bool = False  # send "dimensions": EMBEDDING_DIM (OpenAI-style truncation)
    embedding_api_style: Literal["openai", "cloudflare"] = "openai"  # cloudflare = native /run/{model} endpoint
    embedding_timeout_s: float = 30.0
    embedding_max_retries: int = Field(default=3, ge=1, le=5)
    embedding_chars_per_token: float = 3.2  # no local tokenizer: conservative estimate for French

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
    # A small, fast model for light jobs (rewriting follow-up questions, describing documents). It has its
    # own rate-limit bucket on Groq, which stretches the free allowance. Used in JSON-object mode.
    llm_light_model: str = "llama-3.1-8b-instant"

    # Who the assistant says it is (shown when a user asks "who are you / who made you?").
    app_name: str = "DocuMind AI"
    creator_name: str = "Saad"
    creator_url: str = ""

    # Chats
    chat_history_messages: int = Field(default=6, ge=0, le=20)  # recent messages used to understand follow-ups

    # Demo accounts: anyone can create one ("Try the demo"); each gets a long random access code.
    # They are limited and expire, to protect the free storage and free AI allowances.
    demo_enabled: bool = True
    demo_max_documents: int = 5
    demo_max_total_bytes: int = 12_000_000
    demo_max_questions_per_day: int = 40
    demo_max_conversations: int = 20
    demo_ttl_days: int = 7  # a demo account with no activity for this long is deleted
    demo_signups_per_ip_per_day: int = 3
    demo_max_active_accounts: int = 300

    # Throttling of wrong access codes (guessing): per hashed client address.
    auth_max_failures: int = 10
    auth_failure_window_minutes: int = 15
    ip_hash_salt: SecretStr = SecretStr("")

    # Secret for the scheduled cleanup endpoint (Vercel cron sends it as a bearer token). Empty = disabled.
    cron_secret: SecretStr = SecretStr("")

    # Question limits
    max_question_chars: int = 2000

    # Worker
    worker_poll_interval_s: float = 1.0
    job_timeout_s: int = 1800
    run_worker_in_api: bool = False  # run the ingestion worker as a thread of the API process
    # Serverless hosting (Vercel): no background thread survives the response, so run queued jobs inside
    # the request that created them (and retry due ones while the client polls the job).
    inline_jobs: bool = False
    db_pool_size: int = Field(default=5, ge=1, le=20)  # per process; keep small on serverless
    db_max_overflow: int = Field(default=5, ge=0, le=20)

    # Browser access (the frontend on another origin, e.g. Vercel). Empty = CORS disabled.
    # Accepts a comma-separated list: CORS_ORIGINS=https://app.vercel.app,http://localhost:5173
    cors_origins: Annotated[list[str], NoDecode] = []

    log_level: str = "INFO"

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: Any) -> Any:
        if isinstance(value, str):
            return [o.strip().rstrip("/") for o in value.split(",") if o.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
