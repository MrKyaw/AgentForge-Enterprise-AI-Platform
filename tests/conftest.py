"""Shared fixtures for the AgentForge test suite."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TypeVar

import pytest

from agentforge.bootstrap import Container, build_container, seed_demo
from agentforge.config import Settings

T = TypeVar("T")

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "data"


def run_async(coro: Awaitable[T]) -> T:
    """Run a coroutine from a synchronous test without a plugin dependency."""
    return asyncio.run(coro)


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    """Isolated settings pointing at a temporary database and the repo corpus."""
    return Settings.load(
        env={},
        db_path=str(tmp_path / "agentforge-test.db"),
        data_dir=DATA_DIR,
        seed_on_startup=False,
        auth_enabled=True,
        daily_budget_usd=25.0,
        model_retry_attempts=2,
        model_retry_backoff_seconds=0.0,
    )


@pytest.fixture()
def container(settings: Settings) -> Container:
    """An empty, isolated platform container."""
    instance = build_container(settings)
    try:
        yield instance
    finally:
        instance.db.close()


@pytest.fixture()
def seeded(container: Container) -> Container:
    """A container with the synthetic corpus ingested exactly once."""
    seed_demo(container)
    return container


@pytest.fixture()
def as_admin(seeded: Container):
    return seeded.principal("admin")


@pytest.fixture()
def as_analyst(seeded: Container):
    return seeded.principal("analyst")


@pytest.fixture()
def admin_headers() -> dict[str, str]:
    return {"X-API-Key": "demo-admin-key"}


@pytest.fixture()
def analyst_headers() -> dict[str, str]:
    return {"X-API-Key": "demo-analyst-key"}


@pytest.fixture()
def viewer_headers() -> dict[str, str]:
    return {"X-API-Key": "viewer-key"}


@pytest.fixture()
def async_runner() -> Callable[[Awaitable[T]], T]:
    return run_async
