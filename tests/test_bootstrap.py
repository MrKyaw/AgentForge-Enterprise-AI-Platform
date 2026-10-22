"""Composition root and demo seeding."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from agentforge.agents.registry import AgentRegistry, builtin_agents
from agentforge.agents.tools import ToolRegistry
from agentforge.bootstrap import (
    _validate_agent_tools,
    build_container,
    seed_demo,
    seed_if_empty,
)
from agentforge.config import Settings
from agentforge.models import AgentSpec

DATA_DIR = Path(__file__).resolve().parents[1] / "data"


def test_container_exposes_the_control_plane(settings: Settings) -> None:
    container = build_container(settings)
    try:
        assert container.knowledge.count_documents() == 0
        assert len(container.agents) == 6
        assert container.providers.available() == {"local"}
        assert container.principal("admin").role == "admin"
        assert container.principal("analyst").is_admin is False
        assert container.principal("viewer").role == "viewer"
        assert set(container.tools.names()) >= {"calculator", "knowledge_search"}
    finally:
        container.db.close()


def test_seed_if_empty_is_idempotent(settings: Settings) -> None:
    container = build_container(settings)
    try:
        first = seed_if_empty(container)
        assert first["ingested"] == 9
        assert first["documents"] == 9

        second = seed_if_empty(container)
        assert second["ingested"] == 0
        assert second["duplicates"] == 0
        assert second["documents"] == 9
    finally:
        container.db.close()


def test_seed_demo_reports_missing_corpus(settings: Settings, tmp_path: Path) -> None:
    container = build_container(settings)
    try:
        report = seed_demo(container, corpus_dir=tmp_path / "missing")
        assert report["error"] == "corpus_missing"
        assert report["ingested"] == 0
    finally:
        container.db.close()


def test_seed_demo_is_idempotent(settings: Settings) -> None:
    container = build_container(settings)
    try:
        first = seed_demo(container, corpus_dir=DATA_DIR / "corpus")
        second = seed_demo(container, corpus_dir=DATA_DIR / "corpus")
        assert first["ingested"] == 9
        assert second["duplicates"] == 9
        assert second["chunks"] == 0
    finally:
        container.db.close()


def test_agent_tool_references_are_validated() -> None:
    tools = ToolRegistry()
    registry = AgentRegistry(
        [
            AgentSpec(
                name="broken-agent",
                display_name="Broken",
                description="References a missing tool.",
                system_prompt="prompt",
                tools=["missing-tool"],
            )
        ]
    )
    with pytest.raises(ValueError, match="unknown tools"):
        _validate_agent_tools(registry, tools)


def test_builtin_agents_reference_only_registered_tools(container) -> None:
    names = set(container.tools.names())
    for agent in builtin_agents():
        assert set(agent.tools) <= names


def test_container_aclose_closes_providers_and_database(settings: Settings) -> None:
    container = build_container(settings)
    asyncio.run(container.aclose())
    assert container.db.ping() is False
