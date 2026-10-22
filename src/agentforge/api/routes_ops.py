"""Models, identity, and platform metadata endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from agentforge import __version__
from agentforge.api.deps import get_container, get_principal
from agentforge.bootstrap import Container
from agentforge.models import Principal

router = APIRouter(prefix="/v1", tags=["Platform"])


@router.get("/models", summary="Model catalog, aliases, and live provider availability")
def list_models(
    _principal: Principal = Depends(get_principal),
    container: Container = Depends(get_container),
) -> dict:
    available = container.providers.available()
    return {
        "models": container.pricing.public_models(available),
        "aliases": container.pricing.aliases,
        "available_providers": sorted(available),
        "offline_mode": available == {"local"},
    }


@router.get("/whoami", summary="Resolve the caller principal")
def whoami(principal: Principal = Depends(get_principal)) -> Principal:
    return principal


@router.get("/version", summary="Platform version")
def version(container: Container = Depends(get_container)) -> dict:
    return {
        "name": "AgentForge",
        "version": __version__,
        "environment": container.settings.environment,
    }
