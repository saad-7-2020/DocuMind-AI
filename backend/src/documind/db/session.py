from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

DEFAULT_CONNECT_TIMEOUT_S = 15


def make_engine(database_url: str) -> Engine:
    # Without a timeout, an unreachable host (e.g. an IPv6-only address from an IPv4 network) makes
    # every connection attempt hang silently. An explicit ?connect_timeout= in the URL wins.
    connect_args = {} if "connect_timeout" in make_url(database_url).query else {
        "connect_timeout": DEFAULT_CONNECT_TIMEOUT_S
    }
    return create_engine(database_url, pool_pre_ping=True, pool_size=5, max_overflow=5, connect_args=connect_args)


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


@contextmanager
def transaction(factory: sessionmaker[Session]) -> Iterator[Session]:
    """One unit of work: commit on success, roll back on any exception."""
    session = factory()
    try:
        yield session
        session.commit()
    except BaseException:
        session.rollback()
        raise
    finally:
        session.close()
