"""FastAPI application factory.

Run with:  uv run documind api   (or: uv run uvicorn --factory documind.api.app:create_app_from_env)
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request, Response

from documind.api.errors import install_error_handlers
from documind.api.routers import documents, health, jobs, query
from documind.config import get_settings
from documind.container import Container, build_container
from documind.observability.logging import configure_logging


def create_app(container: Container) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        container.close()

    app = FastAPI(
        title="DocuMind AI",
        version="0.2.0",
        description="Upload documents, ask questions, get answers grounded in your documents with citations.",
        lifespan=lifespan,
    )
    app.state.container = container

    @app.middleware("http")
    async def request_id(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        rid = uuid.uuid4().hex
        request.state.request_id = rid
        structlog.contextvars.bind_contextvars(request_id=rid)
        try:
            response = await call_next(request)
        finally:
            structlog.contextvars.clear_contextvars()
        response.headers["X-Request-ID"] = rid
        return response

    install_error_handlers(app)
    for r in (health.router, documents.router, jobs.router, query.router):
        app.include_router(r)
    return app


def create_app_from_env() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    return create_app(build_container(settings))
