"""Typed errors. Each carries a stable machine-readable `code`.

Pipeline errors are mapped to job `error_code`s by the worker and to RFC 9457
problem+json responses by the API. Messages must never contain document text.
"""

from __future__ import annotations


class DocuMindError(Exception):
    code = "internal_error"
    status = 500
    title = "Internal error"
    retryable = False

    def __init__(self, detail: str | None = None, **extra: object) -> None:
        super().__init__(detail or self.title)
        self.detail = detail or self.title
        self.extra = extra


# ── Upload validation (API) ──────────────────────────────
class UnsupportedFileType(DocuMindError):
    code, status, title = "unsupported_file_type", 415, "Unsupported file type"


class FileTooLarge(DocuMindError):
    code, status, title = "file_too_large", 413, "File too large"


class EmptyFile(DocuMindError):
    code, status, title = "empty_file", 400, "Empty file"


class DuplicateDocument(DocuMindError):
    code, status, title = "duplicate", 409, "Document already uploaded"


# ── Processing (worker) ──────────────────────────────────
class ExtractionError(DocuMindError):
    code, status, title = "extraction_failed", 422, "Could not extract text"


class PdfEncrypted(ExtractionError):
    code, title = "pdf_encrypted", "PDF is password-protected"


class TooManyPages(ExtractionError):
    code, title = "too_many_pages", "Document has too many pages"


class NoTextFound(ExtractionError):
    code, title = "no_text_found", "No extractable text (OCR arrives in Phase 3)"


# ── Generic API errors ───────────────────────────────────
class NotFound(DocuMindError):
    code, status, title = "not_found", 404, "Not found"


class Unauthorized(DocuMindError):
    code, status, title = "unauthorized", 401, "Missing or invalid API key"


class BadRequest(DocuMindError):
    code, status, title = "bad_request", 400, "Bad request"


class Conflict(DocuMindError):
    code, status, title = "conflict", 409, "Conflict"


# ── LLM ──────────────────────────────────────────────────
class LLMError(DocuMindError):
    code, status, title = "llm_error", 502, "LLM provider error"


class LLMTimeout(LLMError):
    code, status, title = "llm_timeout", 504, "LLM provider timed out"
    retryable = True


class LLMRateLimited(LLMError):
    code, status, title = "llm_rate_limited", 429, "LLM provider rate limit reached"
    retryable = True


class LLMBadOutput(LLMError):
    code, status, title = "llm_bad_output", 502, "LLM returned invalid structured output"
