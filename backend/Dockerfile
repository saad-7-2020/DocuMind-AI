# Production image for the API (and, with RUN_WORKER_IN_API=true, the ingestion worker thread).
# No PyTorch: production uses hosted embeddings (EMBEDDER=openai_compat), so the image stays small
# enough for a 512 MB instance. The local-model dependencies live in the optional `ml` extra.
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_CACHE_DIR=/tmp/uv-cache \
    PATH="/opt/venv/bin:$PATH"

RUN pip install --no-cache-dir uv==0.13.1

WORKDIR /app
# Dependencies first (cached layer), then the code.
COPY pyproject.toml uv.lock ./
COPY src ./src
RUN uv sync --frozen --no-dev && rm -rf /tmp/uv-cache
COPY alembic.ini ./
COPY migrations ./migrations

RUN useradd --create-home --uid 1000 app && mkdir -p /tmp/documind && chown -R app /app /tmp/documind
USER app

# Render injects $PORT. Migrations run on every start: they are idempotent, and with one
# instance there is no race between replicas.
EXPOSE 10000
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn --factory documind.api.app:create_app_from_env --host 0.0.0.0 --port ${PORT:-10000}"]
