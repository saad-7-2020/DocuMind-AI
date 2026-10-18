"""Structured JSON logs that never contain document content, questions or secrets.

Logs say *what happened* (ids, stages, durations, error codes), never *what the
document said*. The redaction processor is a safety net: code shouldn't log these
fields at all, but if someone does, they are replaced before output.
"""

from __future__ import annotations

import logging
import sys

import structlog

REDACTED_KEYS = frozenset({
    "text", "question", "answer", "quote", "content", "prompt", "messages",
    "authorization", "api_key", "groq_api_key", "password",
})


def redact(_logger: object, _method: str, event_dict: dict) -> dict:
    for key in list(event_dict):
        if key.lower() in REDACTED_KEYS:
            event_dict[key] = "[redacted]"
    return event_dict


def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level.upper())
    # HTTP client libraries log every request URL at INFO: noise, and storage URLs carry object keys.
    for noisy in ("httpx", "httpcore", "huggingface_hub", "urllib3", "sentence_transformers"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            redact,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level.upper())),
        cache_logger_on_first_use=True,
    )
