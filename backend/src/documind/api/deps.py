from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from documind.auth import user_for_key
from documind.container import Container
from documind.db.tables import User
from documind.domain.errors import Unauthorized

_bearer = HTTPBearer(auto_error=False)


def get_container(request: Request) -> Container:
    return request.app.state.container


ContainerDep = Annotated[Container, Depends(get_container)]


def current_user(
    container: ContainerDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> User:
    if credentials is None or not credentials.credentials:
        raise Unauthorized()
    with container.sf() as s:
        user = user_for_key(s, credentials.credentials)
    if user is None:
        raise Unauthorized()
    return user


UserDep = Annotated[User, Depends(current_user)]
