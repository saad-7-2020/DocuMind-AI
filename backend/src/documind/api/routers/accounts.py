"""Who am I, the self-service demo sign-up, and the scheduled cleanup."""

from __future__ import annotations

import hmac
from datetime import timedelta

from fastapi import APIRouter, Header, Request

from documind.api.deps import ContainerDep, UserDep, client_ip
from documind.api.schemas import AccountLimits, AccountUsage, DemoCreated, MeOut
from documind.domain.errors import NotFound, Unauthorized

router = APIRouter(tags=["accounts"])


@router.get("/v1/me", response_model=MeOut)
def me(container: ContainerDep, user: UserDep) -> MeOut:
    limits = container.accounts.limits_for(user)
    demo = user.kind == "demo"
    return MeOut(
        kind=user.kind,
        label="Demo" if demo else user.email,
        created_at=user.created_at,
        expires_at=user.last_active_at + timedelta(days=container.settings.demo_ttl_days) if demo else None,
        limits=AccountLimits(**limits) if limits else None,
        usage=AccountUsage(**container.accounts.usage(user)),
    )


@router.post("/v1/demo", status_code=201, response_model=DemoCreated)
def create_demo(request: Request, container: ContainerDep) -> DemoCreated:
    """Public: create a private, limited, expiring demo account and return its access code (shown once)."""
    _, code = container.accounts.create_demo(container.accounts.hash_ip(client_ip(request)))
    return DemoCreated(access_code=code, expires_in_days=container.settings.demo_ttl_days,
                       limits=AccountLimits(**container.accounts.limits()))


@router.get("/internal/cleanup", include_in_schema=False)
def cleanup(container: ContainerDep, authorization: str | None = Header(default=None)) -> dict:
    """Called daily by the host's scheduler (Vercel cron sends `Authorization: Bearer $CRON_SECRET`)."""
    secret = container.settings.cron_secret.get_secret_value()
    if not secret:
        raise NotFound("Not found.")
    supplied = (authorization or "").removeprefix("Bearer ").strip()
    if not hmac.compare_digest(supplied.encode(), secret.encode()):
        raise Unauthorized()
    return {"purged": container.accounts.purge_expired()}
