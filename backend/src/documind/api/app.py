"""FastAPI application factory.

Run with:  uv run documind api   (or: uv run uvicorn --factory documind.api.app:create_app_from_env)
"""

from __future__ import annotations

import threading
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from documind.api.errors import install_error_handlers
from documind.api.routers import accounts, chats, documents, health, jobs, query
from documind.config import get_settings
from documind.container import Container, build_container
from documind.observability.logging import configure_logging


def create_app(container: Container) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        # Single-service deployments (e.g. Render's free tier has no background workers) run the
        # ingestion worker as a thread of this process. If the host stops the process mid-job,
        # the job's lock goes stale and is reclaimed on the next start.
        stop = threading.Event()
        worker_thread: threading.Thread | None = None
        if container.settings.run_worker_in_api:
            worker_thread = threading.Thread(
                target=container.worker.run_forever, args=(stop,), name="documind-worker", daemon=True
            )
            worker_thread.start()
        yield
        stop.set()
        if worker_thread is not None:
            worker_thread.join(timeout=10)
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
    for r in (health.router, documents.router, jobs.router, query.router, chats.router, accounts.router):
        app.include_router(r)

    @app.get("/", include_in_schema=False)
    def root() -> dict:
        """A friendly front door for anyone who opens the API's address in a browser."""
        return {"name": "DocuMind AI API", "docs": "/docs", "health": "/health/ready"}

    # Added last so it is the outermost middleware: CORS headers also reach error responses.
    # Authentication uses a bearer header, not cookies, so credentials are not allowed cross-origin.
    if container.settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=container.settings.cors_origins,
            allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type"],
            expose_headers=["X-Request-ID"],
            max_age=600,
        )
    return app


def create_app_from_env() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    return create_app(build_container(settings))
