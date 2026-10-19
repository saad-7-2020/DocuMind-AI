"""Accounts: demo sign-up, per-account limits, activity tracking and expiry.

Owner accounts (created with the CLI) have no limits. Demo accounts are self-service: each gets a long
random access code, a few documents, a daily question allowance, and is deleted after a period of
inactivity. These limits protect the free tiers (storage, AI allowances); they are not there to annoy visitors.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session, sessionmaker

from documind.auth import create_demo_user, record_auth_failure
from documind.config import Settings
from documind.db.session import transaction
from documind.db.tables import Conversation, Document, Message, User
from documind.domain.errors import DemoUnavailable, QuotaExceeded
from documind.ingestion.storage import BlobStore

log = structlog.get_logger(__name__)


class AccountService:
    def __init__(self, sf: sessionmaker[Session], blobs: BlobStore, settings: Settings) -> None:
        self.sf = sf
        self.blobs = blobs
        self.settings = settings

    def hash_ip(self, ip: str) -> str:
        """Addresses are only ever stored as a salted hash."""
        salt = self.settings.ip_hash_salt.get_secret_value()
        return hashlib.sha256(f"{salt}:{ip}".encode()).hexdigest()[:32]

    # ── limits and usage ─────────────────────────────────
    def limits(self) -> dict[str, int]:
        s = self.settings
        return {
            "max_documents": s.demo_max_documents,
            "max_total_bytes": s.demo_max_total_bytes,
            "max_questions_per_day": s.demo_max_questions_per_day,
            "max_conversations": s.demo_max_conversations,
        }

    def limits_for(self, user: User) -> dict[str, int] | None:
        return self.limits() if user.kind == "demo" else None

    def usage(self, user: User) -> dict[str, int]:
        day_ago = datetime.now(UTC) - timedelta(days=1)
        with self.sf() as s:
            docs, size = s.execute(
                select(func.count(), func.coalesce(func.sum(Document.size_bytes), 0))
                .where(Document.owner_id == user.id, Document.status != "deleting")
            ).one()
            questions = s.scalar(
                select(func.count()).select_from(Message)
                .where(Message.owner_id == user.id, Message.role == "user", Message.created_at > day_ago)
            )
            chats = s.scalar(select(func.count()).select_from(Conversation).where(Conversation.owner_id == user.id))
        return {"documents": int(docs), "total_bytes": int(size), "questions_today": int(questions or 0),
                "conversations": int(chats or 0)}

    def check_can_upload(self, user: User, new_bytes: int) -> None:
        limits = self.limits_for(user)
        if limits is None:
            return
        used = self.usage(user)
        if used["documents"] >= limits["max_documents"]:
            raise QuotaExceeded("Demo accounts can store a few documents. Delete one to add another.",
                                limit="documents", max=limits["max_documents"], used=used["documents"])
        if used["total_bytes"] + new_bytes > limits["max_total_bytes"]:
            raise QuotaExceeded("This would exceed the storage allowed for a demo account.",
                                limit="total_bytes", max=limits["max_total_bytes"], used=used["total_bytes"])

    def check_can_create_conversation(self, user: User) -> None:
        limits = self.limits_for(user)
        if limits is None:
            return
        used = self.usage(user)["conversations"]
        if used >= limits["max_conversations"]:
            raise QuotaExceeded("Demo accounts can keep a limited number of chats. Delete one to start another.",
                                limit="conversations", max=limits["max_conversations"], used=used)

    def check_can_ask(self, user: User) -> None:
        limits = self.limits_for(user)
        if limits is None:
            return
        used = self.usage(user)["questions_today"]
        if used >= limits["max_questions_per_day"]:
            raise QuotaExceeded("Daily question limit reached for this demo account. Please come back tomorrow.",
                                limit="questions_per_day", max=limits["max_questions_per_day"], used=used)

    # ── activity and failures ────────────────────────────
    def touch(self, user: User) -> None:
        """Record that a demo account is in use (at most once an hour), so it isn't expired."""
        if user.kind != "demo":
            return
        with transaction(self.sf) as s:
            s.execute(
                text("UPDATE users SET last_active_at = now() "
                     "WHERE id = :id AND kind = 'demo' AND last_active_at < now() - interval '1 hour'"),
                {"id": user.id},
            )

    def record_failure(self, ip_hash: str) -> None:
        with transaction(self.sf) as s:
            record_auth_failure(s, ip_hash)

    # ── demo sign-up and expiry ──────────────────────────
    def create_demo(self, ip_hash: str | None) -> tuple[User, str]:
        cfg = self.settings
        if not cfg.demo_enabled:
            raise DemoUnavailable("Demo accounts are turned off.")
        self.purge_expired(limit=20)  # lazy cleanup: free room before adding someone new
        with transaction(self.sf) as s:
            active = s.scalar(select(func.count()).select_from(User).where(User.kind == "demo")) or 0
            if active >= cfg.demo_max_active_accounts:
                raise DemoUnavailable("The demo is full right now. Please try again later.")
            if ip_hash:
                recent = s.scalar(
                    select(func.count()).select_from(User).where(
                        User.kind == "demo", User.created_ip_hash == ip_hash,
                        User.created_at > datetime.now(UTC) - timedelta(days=1))
                ) or 0
                if recent >= cfg.demo_signups_per_ip_per_day:
                    raise DemoUnavailable(
                        "Too many demo accounts were created from your network today. "
                        "Reuse the access code you already have, or try again tomorrow.")
            return create_demo_user(s, ip_hash)

    def purge_expired(self, limit: int = 50) -> int:
        """Delete demo accounts idle for `demo_ttl_days`, with their documents and stored files."""
        cutoff = datetime.now(UTC) - timedelta(days=self.settings.demo_ttl_days)
        with transaction(self.sf) as s:
            ids = list(s.scalars(
                select(User.id).where(User.kind == "demo", User.last_active_at < cutoff).limit(limit)))
            if not ids:
                return 0
            keys = set(s.scalars(select(Document.storage_key).where(Document.owner_id.in_(ids))))
            s.execute(delete(User).where(User.id.in_(ids)))  # documents, chunks, jobs and chats cascade
        for key in keys:  # files are shared by content hash: remove one only if no document still uses it
            with self.sf() as s:
                if s.scalar(select(func.count()).select_from(Document).where(Document.storage_key == key)):
                    continue
            try:
                self.blobs.delete(key)
            except Exception as e:
                log.warning("purge_blob_failed", error_type=type(e).__name__)
        log.info("demo_accounts_purged", count=len(ids))
        return len(ids)
