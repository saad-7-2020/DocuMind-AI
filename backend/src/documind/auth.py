"""API keys: random, shown once, stored only as a SHA-256 hash.

A fast hash is fine here (unlike passwords): keys have 256 bits of entropy, so
brute-forcing a leaked hash is infeasible.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from documind.db.tables import ApiKey, AuthFailure, User

KEY_PREFIX = "dm_"
DEMO_PREFIX = "docu-mind"
DEMO_CODE_CHARS = 10  # 36**10 is about 3.6e15 possibilities; guessing is also throttled
_DEMO_ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789"


def generate_api_key() -> str:
    return KEY_PREFIX + secrets.token_urlsafe(32)


def generate_demo_code() -> str:
    """A personal access code like docu-mindk43trs8q2m. With no password, the code IS the secret."""
    return DEMO_PREFIX + "".join(secrets.choice(_DEMO_ALPHABET) for _ in range(DEMO_CODE_CHARS))


def normalize_credential(raw: str) -> str:
    """Tolerate copy/paste noise. Demo codes are case-insensitive; owner keys (dm_...) are exact."""
    key = raw.strip()
    if key.lower().startswith(DEMO_PREFIX):
        return "".join(key.lower().split())
    return key


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
        .where(ApiKey.key_hash == hash_api_key(normalize_credential(key)), ApiKey.revoked_at.is_(None))
    )


def create_demo_user(session: Session, ip_hash: str | None) -> tuple[User, str]:
    """A self-service demo account. The email is a random placeholder: the code is never stored in clear."""
    code = generate_demo_code()
    user = User(id=uuid.uuid4(), email=f"demo-{uuid.uuid4().hex[:12]}@demo.invalid", kind="demo",
                created_ip_hash=ip_hash)
    session.add(user)
    session.flush()
    session.add(ApiKey(user_id=user.id, key_prefix=code[: len(DEMO_PREFIX) + 5], key_hash=hash_api_key(code)))
    return user, code


@dataclass(frozen=True)
class AuthResult:
    user: User | None
    blocked: bool  # too many recent wrong codes from this address


def authenticate(session: Session, key: str, ip_hash: str, max_failures: int, window_minutes: int) -> AuthResult:
    """Look the credential up and read this address's recent failures in a single round trip."""
    cutoff = datetime.now(UTC) - timedelta(minutes=window_minutes)
    failures = (
        select(func.count()).select_from(AuthFailure)
        .where(AuthFailure.ip_hash == ip_hash, AuthFailure.created_at > cutoff).scalar_subquery()
    )
    row = session.execute(
        select(User, failures).select_from(ApiKey).join(User, ApiKey.user_id == User.id)
        .where(ApiKey.key_hash == hash_api_key(normalize_credential(key)), ApiKey.revoked_at.is_(None))
    ).first()
    if row is not None:
        user, fails = row
        return AuthResult(user=None if fails >= max_failures else user, blocked=fails >= max_failures)
    fails = session.scalar(
        select(func.count()).select_from(AuthFailure)
        .where(AuthFailure.ip_hash == ip_hash, AuthFailure.created_at > cutoff)
    ) or 0
    return AuthResult(user=None, blocked=fails >= max_failures)


def record_auth_failure(session: Session, ip_hash: str) -> None:
    session.add(AuthFailure(ip_hash=ip_hash))
    if secrets.randbelow(50) == 0:  # housekeeping: forget failures older than a day
        session.execute(delete(AuthFailure).where(AuthFailure.created_at < datetime.now(UTC) - timedelta(days=1)))


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
