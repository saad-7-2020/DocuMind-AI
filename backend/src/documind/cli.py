"""Command line entry point: `uv run documind <command>`.

  create-user EMAIL   create a user and print a new API key (shown once)
  worker              run the ingestion worker until Ctrl+C
  api                 run the HTTP API (uvicorn)
  doctor              check that the database, storage, embeddings and LLM settings work
"""

from __future__ import annotations

import argparse
import signal
import threading

from documind.config import get_settings
from documind.observability.logging import configure_logging


def _create_user(email: str) -> None:
    from documind.auth import create_user_with_key
    from documind.db.session import make_engine, make_session_factory, transaction

    engine = make_engine(get_settings().database_url)
    with transaction(make_session_factory(engine)) as s:
        user, key = create_user_with_key(s, email)
    engine.dispose()
    print(f"user_id: {user.id}")
    print(f"api_key: {key}")
    print("Store this key now; it cannot be shown again.")


def _worker() -> None:
    from documind.container import build_container

    settings = get_settings()
    container = build_container(settings)
    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    try:
        container.worker.run_forever(stop)
    finally:
        container.close()


def _doctor(skip_embeddings: bool, skip_llm: bool) -> int:
    from documind.container import build_container
    from documind.doctor import doctor_steps

    settings = get_settings()
    container = build_container(settings)
    checks = []
    try:
        # Announce each step before running it, so a slow or stuck one is visible instead of silent.
        for label, step in doctor_steps(skip_embeddings=skip_embeddings, skip_llm=skip_llm):
            print(f"... checking {label}", flush=True)
            c = step(container, settings)
            checks.append(c)
            print(f"[{' OK' if c.ok else 'FAIL'}] {c.name:<11} {c.detail}", flush=True)
            if c.hint and not c.ok:
                print(f"       -> {c.hint}", flush=True)
    finally:
        container.close()
    failed = [c.name for c in checks if not c.ok]
    print()
    print("All checks passed." if not failed else f"{len(failed)} check(s) failed: {', '.join(failed)}")
    return 1 if failed else 0


def _api(host: str, port: int, reload: bool) -> None:
    import uvicorn

    uvicorn.run("documind.api.app:create_app_from_env", factory=True, host=host, port=port, reload=reload)


def main() -> None:
    parser = argparse.ArgumentParser(prog="documind")
    sub = parser.add_subparsers(dest="command", required=True)
    p_user = sub.add_parser("create-user", help="create a user and print an API key")
    p_user.add_argument("email")
    sub.add_parser("worker", help="run the ingestion worker")
    p_api = sub.add_parser("api", help="run the HTTP API")
    p_api.add_argument("--host", default="127.0.0.1")
    p_api.add_argument("--port", type=int, default=8000)
    p_api.add_argument("--reload", action="store_true")
    p_doc = sub.add_parser("doctor", help="check database, storage, embeddings and LLM settings")
    p_doc.add_argument("--skip-embeddings", action="store_true", help="don't call the embedding model/API")
    p_doc.add_argument("--skip-llm", action="store_true", help="don't call the LLM (saves a few tokens)")
    args = parser.parse_args()

    configure_logging(get_settings().log_level)
    if args.command == "create-user":
        _create_user(args.email)
    elif args.command == "worker":
        _worker()
    elif args.command == "api":
        _api(args.host, args.port, args.reload)
    elif args.command == "doctor":
        raise SystemExit(_doctor(args.skip_embeddings, args.skip_llm))


if __name__ == "__main__":
    main()
