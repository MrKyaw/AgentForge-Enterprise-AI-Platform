"""Tool registry, JSON-schema validation, and the built-in tool handlers."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from agentforge.agents.registry import builtin_agents
from agentforge.agents.tools import (
    ToolContext,
    ToolDefinition,
    ToolRegistry,
    build_default_tools,
    validate_arguments,
)
from agentforge.errors import ToolError
from agentforge.models import AgentSpec


def _agent(name: str = "research-copilot") -> AgentSpec:
    return next(agent for agent in builtin_agents() if agent.name == name)


@pytest.fixture()
def tools() -> ToolRegistry:
    data_dir = Path(__file__).resolve().parents[1] / "data"
    return build_default_tools(data_dir)


def _context(tools: ToolRegistry, agent: AgentSpec | None = None) -> ToolContext:
    return ToolContext(
        tenant="demo",
        actor="key_analyst",
        agent=agent or _agent(),
        data=tools.data,
    )


def test_default_tools_are_registered(tools: ToolRegistry) -> None:
    assert tools.names() == sorted(
        [
            "calculator",
            "portfolio_lookup",
            "lookup_client",
            "create_rebalance_task",
            "create_service_ticket",
            "model_selector",
            "knowledge_search",
        ]
    )
    schemas = tools.schemas(["calculator", "model_selector"])
    assert [schema.name for schema in schemas] == ["calculator", "model_selector"]
    assert tools.get("calculator") is not None
    assert tools.get("missing") is None


def test_duplicate_registration_is_rejected(tools: ToolRegistry) -> None:
    definition = tools.get("calculator")
    assert definition is not None
    with pytest.raises(ValueError, match="Duplicate"):
        tools.register(definition)


def test_unknown_tool_schema_and_invocation(tools: ToolRegistry) -> None:
    with pytest.raises(ToolError, match="unknown tool"):
        tools.schemas(["missing"])
    execution = tools.invoke("missing", {}, _context(tools))
    assert execution.ok is False
    assert "Unknown tool" in (execution.error or "")


def test_calculator_evaluates_arithmetic(tools: ToolRegistry) -> None:
    execution = tools.invoke("calculator", {"expression": "24,800,000 * 0.05"}, _context(tools))
    assert execution.ok is True
    assert execution.output["result"] == 1_240_000
    assert execution.output["formatted"] == "1,240,000"
    assert execution.duration_ms >= 0


def test_calculator_supports_approved_functions(tools: ToolRegistry) -> None:
    execution = tools.invoke("calculator", {"expression": "sqrt(81) + max(2, 3)"}, _context(tools))
    assert execution.ok is True
    assert execution.output["result"] == 12
    assert execution.output["formatted"] == "12"


@pytest.mark.parametrize(
    "expression",
    [
        "1 / 0",
        "__import__('os')",
        "2 ** 40",
        "x + 1",
        "1; 2",
        "abs(-2, key=1)",
        "1" * 101,
    ],
)
def test_calculator_rejects_unsafe_or_invalid_expression(
    tools: ToolRegistry, expression: str
) -> None:
    execution = tools.invoke("calculator", {"expression": expression}, _context(tools))
    assert execution.ok is False
    assert execution.error


def test_calculator_rejects_non_finite_and_huge_results(tools: ToolRegistry) -> None:
    infinite = tools.invoke("calculator", {"expression": "exp(1000)"}, _context(tools))
    assert infinite.ok is False
    assert "Calculation failed" in (infinite.error or "")

    huge = tools.invoke("calculator", {"expression": "10 ** 12 * 10 ** 12"}, _context(tools))
    assert huge.ok is False
    assert "magnitude" in (huge.error or "")


def test_portfolio_lookup(tools: ToolRegistry) -> None:
    execution = tools.invoke("portfolio_lookup", {"portfolio_id": "nw-1042"}, _context(tools))
    assert execution.ok is True
    assert execution.output["portfolio_id"] == "NW-1042"
    assert execution.output["market_value_cad"] == 24_800_000
    assert execution.output["market_value_formatted"] == "24,800,000"
    assert len(execution.output["top_holdings"]) == 3

    missing = tools.invoke("portfolio_lookup", {"portfolio_id": "ZZ-0000"}, _context(tools))
    assert missing.ok is False
    assert "Portfolio not found" in (missing.error or "")


def test_client_lookup(tools: ToolRegistry) -> None:
    execution = tools.invoke("lookup_client", {"client_id": "cl-1001"}, _context(tools))
    assert execution.ok is True
    assert execution.output["name"] == "Northlight Foundation"
    assert execution.output["service_tier"] == "Institutional"

    missing = tools.invoke("lookup_client", {"client_id": "CL-9999"}, _context(tools))
    assert missing.ok is False
    assert "Client not found" in (missing.error or "")


def test_rebalance_task_validation(tools: ToolRegistry) -> None:
    context = _context(tools, _agent("portfolio-ops-copilot"))
    created = tools.invoke(
        "create_rebalance_task",
        {
            "portfolio_id": "NW-1042",
            "reason": "drift",
            "target_weights": {"A": 0.6, "B": 0.4},
        },
        context,
    )
    assert created.ok is True
    assert created.requires_approval is True
    assert created.output["status"] == "created"
    assert created.output["requested_by"] == "key_analyst"

    bad_weights = tools.invoke(
        "create_rebalance_task",
        {"portfolio_id": "NW-1042", "reason": "drift", "target_weights": {"A": 0.5}},
        context,
    )
    assert bad_weights.ok is False
    assert "sum to approximately" in (bad_weights.error or "")

    missing = tools.invoke(
        "create_rebalance_task", {"portfolio_id": "ZZ-1", "reason": "drift"}, context
    )
    assert missing.ok is False


def test_service_ticket_validation(tools: ToolRegistry) -> None:
    context = _context(tools, _agent("client-service-copilot"))
    created = tools.invoke(
        "create_service_ticket",
        {"client_id": "CL-1001", "summary": "Complaint", "priority": "high"},
        context,
    )
    assert created.ok is True
    assert created.requires_approval is True
    assert created.output["status"] == "open"

    invalid_priority = tools.invoke(
        "create_service_ticket",
        {"client_id": "CL-1001", "summary": "Complaint", "priority": "urgent"},
        context,
    )
    assert invalid_priority.ok is False
    assert "must be one of" in (invalid_priority.error or "")

    missing = tools.invoke(
        "create_service_ticket",
        {"client_id": "CL-9999", "summary": "Complaint", "priority": "low"},
        context,
    )
    assert missing.ok is False
    assert "Client not found" in (missing.error or "")


@pytest.mark.parametrize(
    ("arguments", "expected"),
    [
        ({"use_case": "analysis", "data_residency": "local"}, "local-grounded"),
        ({"use_case": "analysis", "data_residency": "canada"}, "azure-gpt-4o"),
        ({"use_case": "complex research"}, "gpt-4.1"),
        ({"use_case": "routine summarization"}, "claude-sonnet-4-5"),
    ],
)
def test_model_selector(tools: ToolRegistry, arguments: dict, expected: str) -> None:
    execution = tools.invoke("model_selector", arguments, _context(tools))
    assert execution.ok is True
    assert execution.output["recommended_model"] == expected
    assert execution.output["tenant"] == "demo"
    assert execution.output["guardrails"]


def test_knowledge_search_requires_knowledge_base(tools: ToolRegistry) -> None:
    execution = tools.invoke("knowledge_search", {"query": "issuer limit"}, _context(tools))
    assert execution.ok is False
    assert "not configured" in (execution.error or "")


def test_validate_arguments_rules() -> None:
    schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "count": {"type": "integer"},
            "ratio": {"type": "number"},
            "flag": {"type": "boolean"},
            "items": {"type": "array"},
            "nested": {"type": "object"},
            "mode": {"type": "string", "enum": ["a", "b"]},
        },
        "required": ["name"],
        "additionalProperties": False,
    }
    validate_arguments(schema, {"name": "ok"})
    with pytest.raises(ToolError, match="Missing required"):
        validate_arguments(schema, {})
    with pytest.raises(ToolError, match="Unexpected"):
        validate_arguments(schema, {"name": "ok", "extra": 1})
    with pytest.raises(ToolError, match="must be a string"):
        validate_arguments(schema, {"name": 1})
    with pytest.raises(ToolError, match="must be an integer"):
        validate_arguments(schema, {"name": "ok", "count": True})
    with pytest.raises(ToolError, match="must be a number"):
        validate_arguments(schema, {"name": "ok", "ratio": "1"})
    with pytest.raises(ToolError, match="must be a boolean"):
        validate_arguments(schema, {"name": "ok", "flag": "yes"})
    with pytest.raises(ToolError, match="must be an array"):
        validate_arguments(schema, {"name": "ok", "items": "no"})
    with pytest.raises(ToolError, match="must be an object"):
        validate_arguments(schema, {"name": "ok", "nested": []})
    with pytest.raises(ToolError, match="one of"):
        validate_arguments(schema, {"name": "ok", "mode": "c"})


def test_registry_wraps_scalar_output(tools: ToolRegistry) -> None:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="scalar",
            description="returns a scalar",
            parameters={"type": "object", "properties": {}, "additionalProperties": False},
            handler=lambda arguments, context: 42,
        )
    )
    execution = registry.invoke("scalar", {}, _context(tools))
    assert execution.ok is True
    assert execution.output == {"result": 42}


def test_registry_rejects_async_handlers(tools: ToolRegistry) -> None:
    async def handler(arguments, context):
        return {"ok": True}

    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="async",
            description="async",
            parameters={"type": "object", "properties": {}, "additionalProperties": False},
            handler=handler,
        )
    )
    execution = registry.invoke("async", {}, _context(tools))
    assert execution.ok is False
    assert "Async" in (execution.error or "")


def test_registry_wraps_argument_errors(tools: ToolRegistry) -> None:
    execution = tools.invoke("calculator", {}, _context(tools))
    assert execution.ok is False
    assert "Missing required argument" in (execution.error or "")

    execution = tools.invoke("calculator", {"expression": "1", "extra": True}, _context(tools))
    assert execution.ok is False
    assert "Unexpected arguments" in (execution.error or "")


def test_handler_exceptions_are_returned_as_errors(tools: ToolRegistry) -> None:
    def failing(arguments, context):
        raise ZeroDivisionError("boom")

    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="failing",
            description="fails",
            parameters={"type": "object", "properties": {}, "additionalProperties": False},
            handler=failing,
        )
    )
    execution = registry.invoke("failing", {}, _context(tools))
    assert execution.ok is False
    assert execution.error == "boom"


def test_awaitable_handlers_are_rejected(tools: ToolRegistry) -> None:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="awaitable",
            description="returns a coroutine",
            parameters={"type": "object", "properties": {}, "additionalProperties": False},
            handler=lambda arguments, context: asyncio.sleep(0),
        )
    )
    execution = registry.invoke("awaitable", {}, _context(tools))
    assert execution.ok is False
    assert "Async" in (execution.error or "")
