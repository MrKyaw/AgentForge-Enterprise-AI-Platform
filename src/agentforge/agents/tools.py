"""Tool registry with JSON-schema validation and approval metadata."""

from __future__ import annotations

import ast
import inspect
import json
import math
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from time import perf_counter
from typing import Any

from agentforge.errors import ToolError
from agentforge.models import (
    AgentSpec,
    Classification,
    ToolExecution,
    ToolSchema,
)
from agentforge.rag.ingest import KnowledgeBase
from agentforge.util import clip, new_id, now_iso

ToolHandler = Callable[[dict[str, Any], "ToolContext"], Any]


@dataclass(slots=True)
class ToolContext:
    tenant: str
    actor: str
    agent: AgentSpec
    knowledge: KnowledgeBase | None = None
    allowed_classifications: set[Classification] = field(default_factory=set)
    approval_id: str | None = None
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ToolDefinition:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: ToolHandler
    requires_approval: bool = False
    risk: str = "low"
    allowed_roles: frozenset[str] = frozenset({"analyst", "admin"})

    def to_schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.name,
            description=self.description,
            parameters=self.parameters,
        )


class ToolRegistry:
    def __init__(self, data: dict[str, Any] | None = None) -> None:
        self._tools: dict[str, ToolDefinition] = {}
        self.data: dict[str, Any] = data or {}

    def register(self, tool: ToolDefinition) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Duplicate tool name: {tool.name}")
        self._tools[tool.name] = tool

    def register_many(self, tools: list[ToolDefinition]) -> None:
        for tool in tools:
            self.register(tool)

    def get(self, name: str) -> ToolDefinition | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return sorted(self._tools)

    def schemas(self, names: list[str]) -> list[ToolSchema]:
        schemas: list[ToolSchema] = []
        for name in names:
            tool = self._tools.get(name)
            if tool is None:
                raise ToolError(f"Agent references an unknown tool: {name}")
            schemas.append(tool.to_schema())
        return schemas

    def invoke(
        self,
        name: str,
        arguments: dict[str, Any],
        context: ToolContext,
    ) -> ToolExecution:
        started = perf_counter()
        tool = self._tools.get(name)
        if tool is None:
            return ToolExecution(
                name=name,
                arguments=arguments,
                ok=False,
                error=f"Unknown tool: {name}",
                duration_ms=(perf_counter() - started) * 1000,
            )
        try:
            validate_arguments(tool.parameters, arguments)
            output = tool.handler(arguments, context)
            if inspect.isawaitable(output):
                close = getattr(output, "close", None)
                if callable(close):
                    close()
                raise ToolError("Async tool handlers must be awaited by the runtime.")
            if not isinstance(output, dict):
                output = {"result": output}
            return ToolExecution(
                name=name,
                arguments=arguments,
                output=output,
                ok=True,
                requires_approval=tool.requires_approval,
                duration_ms=(perf_counter() - started) * 1000,
            )
        except (ToolError, ValueError, KeyError, TypeError, ZeroDivisionError) as exc:
            return ToolExecution(
                name=name,
                arguments=arguments,
                ok=False,
                error=str(exc),
                requires_approval=tool.requires_approval,
                duration_ms=(perf_counter() - started) * 1000,
            )


def validate_arguments(schema: dict[str, Any], arguments: dict[str, Any]) -> None:
    """Validate a small, security-relevant subset of JSON Schema."""
    if not isinstance(arguments, dict):
        raise ToolError("Tool arguments must be an object.")
    properties: dict[str, Any] = schema.get("properties", {})
    required: list[str] = schema.get("required", [])
    for name in required:
        if name not in arguments:
            raise ToolError(f"Missing required argument: {name}")
    if schema.get("additionalProperties", False) is False:
        extras = set(arguments) - set(properties)
        if extras:
            raise ToolError(f"Unexpected arguments: {sorted(extras)}")
    for name, value in arguments.items():
        spec = properties.get(name)
        if not spec:
            continue
        expected = spec.get("type")
        if expected == "string" and not isinstance(value, str):
            raise ToolError(f"Argument '{name}' must be a string.")
        if expected == "boolean" and not isinstance(value, bool):
            raise ToolError(f"Argument '{name}' must be a boolean.")
        if expected == "integer" and (not isinstance(value, int) or isinstance(value, bool)):
            raise ToolError(f"Argument '{name}' must be an integer.")
        if expected == "number" and (not isinstance(value, int | float) or isinstance(value, bool)):
            raise ToolError(f"Argument '{name}' must be a number.")
        if expected == "array" and not isinstance(value, list):
            raise ToolError(f"Argument '{name}' must be an array.")
        if expected == "object" and not isinstance(value, dict):
            raise ToolError(f"Argument '{name}' must be an object.")
        enum = spec.get("enum")
        if enum is not None and value not in enum:
            raise ToolError(f"Argument '{name}' must be one of {enum}.")


def _object_schema(
    properties: dict[str, Any],
    required: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required or [],
        "additionalProperties": False,
    }


def _calculator(arguments: dict[str, Any], _context: ToolContext) -> dict[str, Any]:
    # Drop thousands separators while preserving argument-separating commas.
    expression = re.sub(r"(?<=\d),(?=\d{3}\b)", "", arguments["expression"].strip())
    if len(expression) > 100:
        raise ToolError("Expression is too long.")
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise ToolError("Expression is not valid arithmetic.") from exc
    allowed_functions = {
        "sqrt": math.sqrt,
        "abs": abs,
        "round": round,
        "min": min,
        "max": max,
        "log": math.log,
        "exp": math.exp,
    }
    allowed_nodes = (
        ast.Expression
        | ast.BinOp
        | ast.UnaryOp
        | ast.Constant
        | ast.Load
        | ast.Call
        | ast.Name
        | ast.Add
        | ast.Sub
        | ast.Mult
        | ast.Div
        | ast.Pow
        | ast.Mod
        | ast.USub
        | ast.UAdd
    )
    for node in ast.walk(tree):
        if isinstance(node, allowed_nodes):
            continue
        raise ToolError(f"Unsupported arithmetic element: {type(node).__name__}")
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in allowed_functions:
                raise ToolError("Only approved math functions may be called.")
            if node.keywords:
                raise ToolError("Keyword arguments are not supported.")
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Pow):
            exponent = node.right
            if (
                isinstance(exponent, ast.Constant)
                and isinstance(exponent.value, int | float)
                and abs(exponent.value) > 12
            ):
                raise ToolError("Exponent is too large.")
    try:
        result = eval(
            compile(tree, "<calculator>", "eval"),
            {"__builtins__": {}},
            allowed_functions,
        )
    except (ArithmeticError, NameError, ValueError, TypeError) as exc:
        raise ToolError(f"Calculation failed: {exc}") from exc
    if not isinstance(result, int | float) or not math.isfinite(float(result)):
        raise ToolError("Calculation did not produce a finite number.")
    if abs(float(result)) > 1e15:
        raise ToolError("Result exceeds the allowed magnitude.")
    numeric = int(result) if isinstance(result, float) and result.is_integer() else result
    formatted = (
        f"{numeric:,.6f}".rstrip("0").rstrip(".") if isinstance(numeric, float) else f"{numeric:,}"
    )
    return {"expression": expression, "result": numeric, "formatted": formatted}


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _find(items: list[dict[str, Any]], key: str, value: str) -> dict[str, Any] | None:
    return next((item for item in items if item.get(key) == value), None)


def _portfolio_lookup(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    portfolios = context.data.get("portfolios", [])
    portfolio = _find(portfolios, "id", arguments["portfolio_id"].upper())
    if portfolio is None:
        raise ToolError(f"Portfolio not found: {arguments['portfolio_id']}")
    return {
        "portfolio_id": portfolio["id"],
        "name": portfolio["name"],
        "market_value_cad": portfolio["market_value_cad"],
        "market_value_formatted": f"{portfolio['market_value_cad']:,}",
        "currency": portfolio.get("currency", "CAD"),
        "as_of": portfolio["as_of"],
        "risk_profile": portfolio["risk_profile"],
        "cash_weight": portfolio["cash_weight"],
        "top_holdings": portfolio.get("holdings", [])[:3],
    }


def _lookup_client(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    clients = context.data.get("clients", [])
    client = _find(clients, "id", arguments["client_id"].upper())
    if client is None:
        raise ToolError(f"Client not found: {arguments['client_id']}")
    return {
        "client_id": client["id"],
        "name": client["name"],
        "segment": client["segment"],
        "aum_cad": client["aum_cad"],
        "advisor": client["advisor"],
        "risk_profile": client["risk_profile"],
        "service_tier": client["service_tier"],
    }


def _create_rebalance_task(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    portfolios = context.data.get("portfolios", [])
    portfolio = _find(portfolios, "id", arguments["portfolio_id"].upper())
    if portfolio is None:
        raise ToolError(f"Portfolio not found: {arguments['portfolio_id']}")
    target_weights = arguments.get("target_weights")
    if target_weights is not None:
        total = sum(float(value) for value in target_weights.values())
        if not 0.99 <= total <= 1.01:
            raise ToolError("Target weights must sum to approximately 1.0.")
    return {
        "task_id": new_id("rbl"),
        "status": "created",
        "portfolio_id": portfolio["id"],
        "requested_by": context.actor,
        "reason": arguments["reason"],
        "target_weights": target_weights or "advisor to confirm",
        "created_at": now_iso(),
        "next_step": "Operations review and advisor confirmation",
    }


def _create_service_ticket(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    clients = context.data.get("clients", [])
    if _find(clients, "id", arguments["client_id"].upper()) is None:
        raise ToolError(f"Client not found: {arguments['client_id']}")
    return {
        "ticket_id": new_id("tkt"),
        "status": "open",
        "client_id": arguments["client_id"].upper(),
        "priority": arguments["priority"],
        "summary": arguments["summary"],
        "created_by": context.actor,
        "created_at": now_iso(),
        "sla": "Acknowledge within two business days",
    }


def _model_selector(_arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    use_case = _arguments["use_case"]
    residency = _arguments.get("data_residency", "global")
    requires_tools = _arguments.get("requires_tools", True)
    lowered = use_case.lower()
    if residency == "local":
        recommendation = "local-grounded"
        rationale = "Data must remain local; use the offline grounded provider."
    elif residency == "canada":
        recommendation = "azure-gpt-4o"
        rationale = "Canadian residency is required; use the in-country Azure deployment."
    elif any(word in lowered for word in ("reasoning", "analysis", "research", "complex")):
        recommendation = "gpt-4.1"
        rationale = "Complex synthesis benefits from a reasoning-tier model."
    else:
        recommendation = "claude-sonnet-4-5"
        rationale = "Balanced quality and cost for general enterprise workflows."
    return {
        "recommended_model": recommendation,
        "fallback_chain": ["azure-gpt-4o", "local-grounded"]
        if residency != "local"
        else ["local-grounded"],
        "requires_tools": requires_tools,
        "rationale": rationale,
        "guardrails": [
            "Route through the model gateway",
            "Enforce tenant budgets and rate limits",
            "Log prompt and response metadata for audit",
        ],
        "tenant": context.tenant,
    }


def _knowledge_search(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    if context.knowledge is None:
        raise ToolError("Knowledge base is not configured.")
    collections = (
        [arguments["collection"]] if arguments.get("collection") else context.agent.collections
    )
    allowed = context.allowed_classifications or {Classification.PUBLIC}
    hits = context.knowledge.search(
        arguments["query"],
        collections=collections,
        top_k=int(arguments.get("top_k", 4)),
        allowed=allowed,
    )
    return {
        "query": arguments["query"],
        "results": [
            {
                "title": hit.title,
                "collection": hit.collection,
                "content": clip(hit.content, 500),
                "score": hit.score,
            }
            for hit in hits
        ],
    }


def build_default_tools(
    data_dir: str | Path, knowledge: KnowledgeBase | None = None
) -> ToolRegistry:
    data_path = Path(data_dir)
    demo_data = {
        "portfolios": _load_json(data_path / "demo" / "portfolios.json", {}).get("portfolios", []),
        "clients": _load_json(data_path / "demo" / "clients.json", {}).get("clients", []),
    }
    tools = [
        ToolDefinition(
            name="calculator",
            description="Evaluate safe arithmetic for sizing, weights, and scenario analysis.",
            parameters=_object_schema(
                {"expression": {"type": "string", "description": "Arithmetic expression"}},
                ["expression"],
            ),
            handler=_calculator,
            risk="low",
        ),
        ToolDefinition(
            name="portfolio_lookup",
            description="Read a synthetic portfolio's valuation, risk profile, and top holdings.",
            parameters=_object_schema(
                {"portfolio_id": {"type": "string", "description": "Portfolio identifier"}},
                ["portfolio_id"],
            ),
            handler=_portfolio_lookup,
            risk="low",
        ),
        ToolDefinition(
            name="lookup_client",
            description="Read a synthetic client's segment, service tier, and advisor.",
            parameters=_object_schema(
                {"client_id": {"type": "string", "description": "Client identifier"}},
                ["client_id"],
            ),
            handler=_lookup_client,
            risk="medium",
        ),
        ToolDefinition(
            name="create_rebalance_task",
            description="Create an operations rebalance task. Requires human approval.",
            parameters=_object_schema(
                {
                    "portfolio_id": {"type": "string"},
                    "reason": {"type": "string"},
                    "target_weights": {
                        "type": "object",
                        "description": "Optional map of ticker to target weight",
                    },
                },
                ["portfolio_id", "reason"],
            ),
            handler=_create_rebalance_task,
            requires_approval=True,
            risk="high",
        ),
        ToolDefinition(
            name="create_service_ticket",
            description="Open a client service ticket. Requires human approval.",
            parameters=_object_schema(
                {
                    "client_id": {"type": "string"},
                    "summary": {"type": "string"},
                    "priority": {
                        "type": "string",
                        "enum": ["low", "normal", "high"],
                    },
                },
                ["client_id", "summary", "priority"],
            ),
            handler=_create_service_ticket,
            requires_approval=True,
            risk="high",
        ),
        ToolDefinition(
            name="model_selector",
            description="Recommend a model tier from residency, complexity, and tool requirements.",
            parameters=_object_schema(
                {
                    "use_case": {"type": "string"},
                    "data_residency": {
                        "type": "string",
                        "enum": ["local", "canada", "global"],
                    },
                    "requires_tools": {"type": "boolean"},
                },
                ["use_case"],
            ),
            handler=_model_selector,
            risk="low",
        ),
        ToolDefinition(
            name="knowledge_search",
            description="Search governed knowledge collections for supporting passages.",
            parameters=_object_schema(
                {
                    "query": {"type": "string"},
                    "collection": {"type": "string"},
                    "top_k": {"type": "integer"},
                },
                ["query"],
            ),
            handler=_knowledge_search,
            risk="low",
        ),
    ]
    registry = ToolRegistry(data=demo_data)
    registry.register_many(tools)
    return registry
