"""The ingestion worker: claim a job, run it, record the outcome, repeat."""

from __future__ import annotations

import os
import socket
import threading

import structlog

from documind.domain.errors import DocuMindError
from documind.domain.models import JobKind
from documind.indexing.service import IndexingService
from documind.ingestion.jobs import ClaimedJob, JobQueue

log = structlog.get_logger(__name__)


class Worker:
    def __init__(self, queue: JobQueue, indexing: IndexingService, job_timeout_s: int,
                 poll_interval_s: float = 1.0) -> None:
        self.queue = queue
        self.indexing = indexing
        self.job_timeout_s = job_timeout_s
        self.poll_interval_s = poll_interval_s
        self.worker_id = f"{socket.gethostname()}:{os.getpid()}"

    def run_once(self) -> bool:
        """Process at most one job. Returns False when no job was ready."""
        job = self.queue.claim(self.worker_id, self.job_timeout_s)
        if job is None:
            return False
        self._process(job)
        return True

    def run_until_empty(self, max_jobs: int = 1000) -> int:
        n = 0
        while n < max_jobs and self.run_once():
            n += 1
        return n

    def run_forever(self, stop: threading.Event) -> None:
        log.info("worker_started", worker_id=self.worker_id)
        while not stop.is_set():
            if not self.run_once():
                stop.wait(self.poll_interval_s)
        log.info("worker_stopped", worker_id=self.worker_id)

    def _process(self, job: ClaimedJob) -> None:
        log.info("job_started", job_id=str(job.id), kind=job.kind.value, attempt=job.attempts)
        try:
            if job.attempts > job.max_attempts:  # reclaimed after a crash too many times
                raise DocuMindError("Job exceeded its maximum attempts.")
            if job.kind in (JobKind.INGEST, JobKind.REINDEX):
                self.indexing.ingest(job)
            elif job.kind == JobKind.DELETE:
                self.indexing.delete(job)
        except Exception as e:
            final = self.queue.fail(job, e)
            code = e.code if isinstance(e, DocuMindError) else "internal_error"
            # Log the error type and code only: messages from parsers could echo document content.
            log.warning("job_failed", job_id=str(job.id), error_code=code, error_type=type(e).__name__,
                        final=final)
            if final and job.kind != JobKind.DELETE:
                self.indexing.mark_failed(job.document_id, code)
            return
        self.queue.succeed(job.id)
        log.info("job_succeeded", job_id=str(job.id))
