"""Durable job queue on a Postgres table.

`SELECT … FOR UPDATE SKIP LOCKED` lets several workers poll the same table: each
claims a different row, and a locked row is skipped instead of waited on. The job
is inserted in the *same transaction* as its document, so "document saved but job
lost" can't happen.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from documind.db.session import transaction
from documind.db.tables import Job
from documind.domain.errors import DocuMindError
from documind.domain.models import JobKind, JobStatus

BACKOFF_BASE_S = 5.0
BACKOFF_MAX_S = 300.0


@dataclass(frozen=True)
class ClaimedJob:
    id: uuid.UUID
    kind: JobKind
    owner_id: uuid.UUID
    document_id: uuid.UUID | None
    attempts: int
    max_attempts: int


_CLAIM_SQL = text("""
UPDATE jobs
SET status = 'running', locked_by = :worker, locked_at = now(),
    attempts = attempts + 1, updated_at = now()
WHERE id = (
    SELECT id FROM jobs
    WHERE (status = 'queued' AND run_after <= now())
       OR (status = 'running' AND locked_at < now() - make_interval(secs => :timeout_s))
    ORDER BY run_after
    FOR UPDATE SKIP LOCKED
    LIMIT 1
)
RETURNING id, kind, owner_id, document_id, attempts, max_attempts
""")


def backoff_seconds(attempts: int) -> float:
    return min(BACKOFF_MAX_S, BACKOFF_BASE_S * 2 ** (attempts - 1))


def is_retryable(error: BaseException) -> bool:
    """Typed pipeline errors say whether they're transient. Unknown errors (DB blips,
    out-of-memory) are retried, since a bounded retry is cheap and often succeeds."""
    if isinstance(error, DocuMindError):
        return error.retryable
    return True


class JobQueue:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.sf = session_factory

    @staticmethod
    def enqueue(session: Session, owner_id: uuid.UUID, document_id: uuid.UUID, kind: JobKind) -> Job:
        """Add a job inside the caller's transaction."""
        job = Job(id=uuid.uuid4(), owner_id=owner_id, document_id=document_id, kind=kind.value)
        session.add(job)
        return job

    def claim(self, worker_id: str, job_timeout_s: int) -> ClaimedJob | None:
        with transaction(self.sf) as s:
            row = s.execute(_CLAIM_SQL, {"worker": worker_id, "timeout_s": job_timeout_s}).one_or_none()
        if row is None:
            return None
        return ClaimedJob(row.id, JobKind(row.kind), row.owner_id, row.document_id, row.attempts, row.max_attempts)

    def set_stage(self, job_id: uuid.UUID, stage: str, progress: float) -> None:
        with transaction(self.sf) as s:
            s.execute(
                text("UPDATE jobs SET stage = :stage, progress = :p, updated_at = now() WHERE id = :id"),
                {"stage": stage, "p": max(0.0, min(1.0, progress)), "id": job_id},
            )

    def succeed(self, job_id: uuid.UUID) -> None:
        with transaction(self.sf) as s:
            s.execute(
                text("""UPDATE jobs SET status = 'succeeded', stage = 'done', progress = 1,
                        locked_by = NULL, locked_at = NULL, last_error = NULL, updated_at = now()
                        WHERE id = :id"""),
                {"id": job_id},
            )

    def fail(self, job: ClaimedJob, error: BaseException) -> bool:
        """Record a failure. Returns True if the failure is final (no more retries)."""
        code = error.code if isinstance(error, DocuMindError) else type(error).__name__
        detail = error.detail if isinstance(error, DocuMindError) else "unexpected error"
        final = not is_retryable(error) or job.attempts >= job.max_attempts
        status = JobStatus.FAILED if final else JobStatus.QUEUED
        with transaction(self.sf) as s:
            s.execute(
                text("""UPDATE jobs SET status = :status, last_error = :err, locked_by = NULL, locked_at = NULL,
                        run_after = now() + make_interval(secs => :delay), updated_at = now()
                        WHERE id = :id"""),
                {
                    "status": status.value,
                    "err": f"{code}: {detail}"[:500],
                    "delay": 0 if final else backoff_seconds(job.attempts),
                    "id": job.id,
                },
            )
        return final
