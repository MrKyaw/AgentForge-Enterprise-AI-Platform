"""FastAPI dependencies."""

from __future__ import annotations

from fastapi import Depends, Request, Security
from fastapi.security import APIKeyHeader

from agentforge.auth import Authenticator
from agentforge.bootstrap import Container
from agentforge.models import Principal

api_key_header = APIKeyHeader(
    name="X-API-Key",
    auto_error=False,
    description="Tenant API key. Bearer tokens are also accepted.",
)


def get_container(request: Request) -> Container:
    return request.app.state.container


async def get_principal(
    request: Request,
    api_key: str | None = Security(api_key_header),
    container: Container = Depends(get_container),
) -> Principal:
    raw = api_key
    if not raw:
        authorization = request.headers.get("Authorization", "")
        if authorization.lower().startswith("bearer "):
            raw = authorization[7:].strip()
    return container.auth.authenticate(raw)


async def get_admin(
    principal: Principal = Depends(get_principal),
) -> Principal:
    Authenticator.require_admin(principal)
    return principal
