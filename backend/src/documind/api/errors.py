"""Map errors to RFC 9457 problem+json responses."""

from __future__ import annotations

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from documind.domain.errors import DocuMindError

log = structlog.get_logger(__name__)
PROBLEM_JSON = "application/problem+json"


def problem(request: Request, status: int, code: str, title: str, detail: str, **extra: object) -> JSONResponse:
    body = {
        "type": f"https://documind.dev/errors/{code.replace('_', '-')}",
        "title": title,
        "status": status,
        "detail": detail,
        "code": code,
        "request_id": getattr(request.state, "request_id", None),
        **extra,
    }
    headers = {"WWW-Authenticate": "Bearer"} if status == 401 else None
    return JSONResponse(body, status_code=status, media_type=PROBLEM_JSON, headers=headers)


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(DocuMindError)
    async def _documind(request: Request, exc: DocuMindError) -> JSONResponse:
        if exc.status >= 500:
            log.warning("request_failed", error_code=exc.code, status=exc.status)
        return problem(request, exc.status, exc.code, exc.title, exc.detail, **exc.extra)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        # Echo locations and messages only, never the submitted values.
        errors = [{"loc": list(e["loc"]), "msg": e["msg"]} for e in exc.errors()]
        return problem(request, 422, "validation_error", "Invalid request", "Request validation failed.",
                       errors=errors)

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, exc: Exception) -> JSONResponse:
        log.error("unhandled_error", error_type=type(exc).__name__)
        return problem(request, 500, "internal_error", "Internal error", "An unexpected error occurred.")
