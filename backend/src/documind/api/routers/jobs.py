from __future__ import annotations

import uuid

from fastapi import APIRouter
from sqlalchemy import select

from documind.api.deps import ContainerDep, UserDep
from documind.api.schemas import JobOut
from documind.db.tables import Job
from documind.domain.errors import NotFound

router = APIRouter(prefix="/v1/jobs", tags=["jobs"])


@router.get("/{job_id}", response_model=JobOut)
def get_job(job_id: uuid.UUID, container: ContainerDep, user: UserDep) -> JobOut:
    with container.sf() as s:
        job = s.scalar(select(Job).where(Job.id == job_id, Job.owner_id == user.id))
    if job is None:
        raise NotFound("Job not found.")
    if job.status == "queued" and container.run_pending_jobs():
        # Serverless mode: a retry that is now due runs while the client polls.
        with container.sf() as s:
            job = s.scalar(select(Job).where(Job.id == job_id, Job.owner_id == user.id)) or job
    return JobOut(
        id=job.id, kind=job.kind, status=job.status, stage=job.stage, progress=job.progress,
        attempts=job.attempts, document_id=job.document_id,
        error_code=job.last_error.split(":", 1)[0] if job.last_error else None,
    )
