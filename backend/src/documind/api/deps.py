from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from documind.auth import authenticate
from documind.container import Container
from documind.db.tables import User
from documind.domain.errors import TooManyAttempts, Unauthorized

_bearer = HTTPBearer(auto_error=False)


def get_container(request: Request) -> Container:
    return request.app.state.container


ContainerDep = Annotated[Container, Depends(get_container)]


def client_ip(request: Request) -> str:
    """The visitor's address. Behind Vercel/proxies the first X-Forwarded-For entry is the client."""
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def current_user(
    request: Request,
    container: ContainerDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> User:
    if credentials is None or not credentials.credentials:
        raise Unauthorized()
    cfg = container.settings
    ip_hash = container.accounts.hash_ip(client_ip(request))
    with container.sf() as s:
        result = authenticate(s, credentials.credentials, ip_hash, cfg.auth_max_failures,
                              cfg.auth_failure_window_minutes)
    if result.user is None:
        if result.blocked:
            raise TooManyAttempts()
        container.accounts.record_failure(ip_hash)  # wrong code: counted, so guessing is throttled
        raise Unauthorized()
    container.accounts.touch(result.user)
    return result.user


UserDep = Annotated[User, Depends(current_user)]
