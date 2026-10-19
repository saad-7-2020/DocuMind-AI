"""API keys: random, shown once, stored only as a SHA-256 hash.

A fast hash is fine here (unlike passwords): keys have 256 bits of entropy, so
brute-forcing a leaked hash is infeasible.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from documind.db.tables import ApiKey, User

KEY_PREFIX = "dm_"


def generate_api_key() -> str:
    return KEY_PREFIX + secrets.token_urlsafe(32)


def hash_api_key(key: str) -> bytes:
    return hashlib.sha256(key.encode()).digest()


def create_user_with_key(session: Session, email: str) -> tuple[User, str]:
    user = User(id=uuid.uuid4(), email=email.strip().lower())
    key = generate_api_key()
    session.add(user)
    session.flush()
    session.add(ApiKey(user_id=user.id, key_prefix=key[:8], key_hash=hash_api_key(key)))
    return user, key


def user_for_key(session: Session, key: str) -> User | None:
    return session.scalar(
        select(User).join(ApiKey, ApiKey.user_id == User.id)
        .where(ApiKey.key_hash == hash_api_key(key), ApiKey.revoked_at.is_(None))
    )


# ── Key management (used by the CLI) ─────────────────────

def create_key(session: Session, email: str) -> str:
    """Issue an additional key for an existing user. The plaintext key is returned once."""
    user = session.scalar(select(User).where(User.email == email.strip().lower()))
    if user is None:
        raise LookupError(f"No user with email {email!r}.")
    key = generate_api_key()
    session.add(ApiKey(user_id=user.id, key_prefix=key[:8], key_hash=hash_api_key(key)))
    return key


def list_keys(session: Session, email: str | None = None) -> list[tuple[str, str, datetime, datetime | None]]:
    """(prefix, user email, created_at, revoked_at): only the prefix is ever shown, never the key."""
    stmt = select(ApiKey.key_prefix, User.email, ApiKey.created_at, ApiKey.revoked_at).join(
        User, User.id == ApiKey.user_id
    )
    if email:
        stmt = stmt.where(User.email == email.strip().lower())
    return [tuple(row) for row in session.execute(stmt.order_by(ApiKey.created_at))]  # type: ignore[misc]


def revoke_key(session: Session, prefix: str) -> int:
    """Revoke the active key that starts with this prefix. Refuses if the prefix is ambiguous."""
    keys = list(session.scalars(select(ApiKey).where(ApiKey.key_prefix == prefix, ApiKey.revoked_at.is_(None))))
    if len(keys) > 1:
        raise ValueError(f"Prefix {prefix!r} matches {len(keys)} active keys; refusing to guess.")
    for k in keys:
        k.revoked_at = datetime.now(UTC)
    return len(keys)
