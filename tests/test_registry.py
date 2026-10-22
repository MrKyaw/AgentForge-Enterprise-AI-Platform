"""Agent registry versioning and tenant-aware discovery."""

from __future__ import annotations

import pytest

from agentforge.agents.registry import AgentRegistry, builtin_agents
from agentforge.errors import NotFoundError
from agentforge.models import AgentSpec


def _spec(name: str = "demo-agent", version: str = "1.0.0", tenants=None) -> AgentSpec:
    return AgentSpec(
        name=name,
        version=version,
        display_name="Demo Agent",
        description="A demo agent.",
        system_prompt="Answer from sources.",
        entitlements=tenants or ["demo"],
    )


def test_builtin_catalogue_is_consistent() -> None:
    agents = builtin_agents()
    assert len(agents) == 6
    assert len({agent.name for agent in agents}) == 6
    for agent in agents:
        assert agent.version == "1.0.0"
        assert agent.system_prompt
        assert agent.tags


def test_register_and_latest_version() -> None:
    registry = AgentRegistry([_spec(version="1.0.0")])
    registry.register(_spec(version="1.1.0"))
    assert registry.get("demo-agent").version == "1.1.0"
    assert registry.get("demo-agent", "1.0.0").version == "1.0.0"
    assert registry.versions("demo-agent") == ["1.0.0", "1.1.0"]
    assert len(registry) == 1


def test_duplicate_version_is_rejected() -> None:
    registry = AgentRegistry([_spec()])
    with pytest.raises(ValueError, match="already exists"):
        registry.register(_spec())


def test_unknown_agent_and_version() -> None:
    registry = AgentRegistry([_spec()])
    with pytest.raises(NotFoundError):
        registry.get("missing")
    with pytest.raises(NotFoundError):
        registry.get("demo-agent", "9.9.9")
    with pytest.raises(NotFoundError):
        registry.versions("missing")


def test_list_filters_by_tenant_and_returns_latest() -> None:
    registry = AgentRegistry(
        [
            _spec("alpha", "1.0.0", ["demo"]),
            _spec("alpha", "2.0.0", ["demo"]),
            _spec("beta", "1.0.0", ["research"]),
        ]
    )
    demo = registry.list(tenant="demo")
    assert [agent.name for agent in demo] == ["alpha"]
    assert demo[0].version == "2.0.0"

    research = registry.list(tenant="research")
    assert [agent.name for agent in research] == ["beta"]

    everything = registry.list(include_all=True)
    assert [agent.name for agent in everything] == ["alpha", "beta"]
    assert len(registry.list()) == 2
    assert registry.list(tenant="unknown") == []
