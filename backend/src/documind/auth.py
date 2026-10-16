"""API keys: random, shown once, stored only as a SHA-256 hash.

A fast hash is fine here (unlike passwords): keys have 256 bits of entropy, so
brute-forcing a leaked hash is infeasible.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid

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
