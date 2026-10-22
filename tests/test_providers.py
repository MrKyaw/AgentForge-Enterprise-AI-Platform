"""Provider adapters: offline grounded synthesis and HTTP vendor clients."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest

from agentforge.errors import ProviderError
from agentforge.gateway.base import CompletionRequest
from agentforge.gateway.providers import (
    AnthropicProvider,
    LocalGroundedProvider,
    OpenAICompatibleProvider,
)
from agentforge.models import Message, Role, ToolCall, ToolSchema

SYSTEM = (
    "Rules.\n\nSOURCES:\n"
    "[1] Concentration Policy [doc_1] :: The maximum single issuer concentration limit "
    "is 5% of the portfolio.\n"
    "[2] Review Standard [doc_2] :: A position above 4.5% must be reviewed by the risk team.\n"
)


def _request(
    query: str,
    *,
    tools: list[ToolSchema] | None = None,
    messages: list[Message] | None = None,
) -> CompletionRequest:
    return CompletionRequest(
        messages=messages
        or [
            Message(role=Role.SYSTEM, content=SYSTEM),
            Message(role=Role.USER, content=query),
        ],
        model="local-grounded",
        tools=tools or [],
    )


def _tool(name: str) -> ToolSchema:
    return ToolSchema(name=name, description=name, parameters={"type": "object", "properties": {}})


def _complete(request: CompletionRequest):
    return asyncio.run(LocalGroundedProvider().complete(request))


def test_grounded_answer_cites_sources() -> None:
    response = _complete(_request("What is the maximum single issuer concentration limit?"))
    assert response.provider == "local"
    assert response.model == "local-grounded"
    assert "[1]" in response.content
    assert "5%" in response.content
    assert response.finish_reason == "stop"
    assert response.usage.prompt_tokens > 0
    assert response.usage.completion_tokens > 0
    assert response.tool_calls == []


def test_refuses_without_sources() -> None:
    request = CompletionRequest(
        messages=[Message(role=Role.USER, content="What is the limit?")], model="local-grounded"
    )
    response = _complete(request)
    assert "don't have enough grounded evidence" in response.content


def test_refuses_when_numbers_are_absent() -> None:
    response = _complete(_request("What was the portfolio return in 2019?"))
    assert "don't have enough grounded evidence" in response.content


def test_refuses_when_query_is_out_of_scope() -> None:
    response = _complete(_request("Explain the lunar landing guidance computer design."))
    assert "don't have enough grounded evidence" in response.content


def test_plans_portfolio_lookup() -> None:
    response = _complete(
        _request(
            "What is the market value of portfolio NW-1042?",
            tools=[_tool("portfolio_lookup")],
        )
    )
    assert response.finish_reason == "tool_calls"
    assert response.content == ""
    assert [call.name for call in response.tool_calls] == ["portfolio_lookup"]
    assert response.tool_calls[0].arguments == {"portfolio_id": "NW-1042"}


def test_plans_client_lookup_and_ticket() -> None:
    response = _complete(
        _request(
            "Open an urgent ticket for client CL-1001 about a complaint.",
            tools=[_tool("lookup_client"), _tool("create_service_ticket")],
        )
    )
    names = [call.name for call in response.tool_calls]
    assert "lookup_client" in names
    assert "create_service_ticket" in names
    ticket = next(call for call in response.tool_calls if call.name == "create_service_ticket")
    assert ticket.arguments["priority"] == "high"


def test_plans_calculator_and_model_selector() -> None:
    calculator = _complete(
        _request(
            "Calculate 24,800,000 * 0.05 for the concentration limit.",
            tools=[_tool("calculator")],
        )
    )
    assert calculator.tool_calls[0].name == "calculator"
    assert calculator.tool_calls[0].arguments["expression"] == "24800000 * 0.05"

    selector = _complete(
        _request(
            "Which model should we use for local analysis?",
            tools=[_tool("model_selector")],
        )
    )
    assert selector.tool_calls[0].name == "model_selector"
    assert selector.tool_calls[0].arguments["data_residency"] == "local"


def test_plans_rebalance_task() -> None:
    response = _complete(
        _request(
            "Rebalance portfolio NW-1042 to target weights.",
            tools=[_tool("portfolio_lookup"), _tool("create_rebalance_task")],
        )
    )
    names = [call.name for call in response.tool_calls]
    assert names == ["portfolio_lookup", "create_rebalance_task"]


def test_does_not_repeat_completed_tools() -> None:
    call = ToolCall(name="portfolio_lookup", arguments={"portfolio_id": "NW-1042"})
    messages = [
        Message(role=Role.SYSTEM, content=SYSTEM),
        Message(role=Role.USER, content="What is the market value of portfolio NW-1042?"),
        Message(role=Role.ASSISTANT, content="", tool_calls=[call]),
        Message(
            role=Role.TOOL,
            name="portfolio_lookup",
            tool_call_id=call.id,
            content=json.dumps({"ok": True, "output": {"market_value_cad": 24800000}}),
        ),
    ]
    response = _complete(
        _request(
            "What is the market value of portfolio NW-1042?",
            tools=[_tool("portfolio_lookup")],
            messages=messages,
        )
    )
    assert response.tool_calls == []
    assert "24800000" in response.content


def test_synthesizes_tool_failures() -> None:
    call = ToolCall(name="portfolio_lookup", arguments={"portfolio_id": "ZZ-1"})
    messages = [
        Message(role=Role.SYSTEM, content=SYSTEM),
        Message(role=Role.USER, content="What is the market value of portfolio ZZ-1?"),
        Message(role=Role.ASSISTANT, content="", tool_calls=[call]),
        Message(
            role=Role.TOOL,
            name="portfolio_lookup",
            tool_call_id=call.id,
            content=json.dumps({"ok": False, "error": "Portfolio not found"}),
        ),
    ]
    response = _complete(
        _request(
            "What is the market value of portfolio ZZ-1?",
            tools=[_tool("portfolio_lookup")],
            messages=messages,
        )
    )
    assert "could not complete" in response.content
    assert "Portfolio not found" in response.content


def test_local_provider_is_always_available() -> None:
    provider = LocalGroundedProvider()
    assert provider.available() is True
    assert asyncio.run(provider.aclose()) is None


# -- OpenAI-compatible ------------------------------------------------------


def _openai_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_openai_success_and_payload() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["json"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "model": "gpt-4.1-mini-2026",
                "choices": [
                    {
                        "message": {"content": "Grounded answer [1]."},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 120, "completion_tokens": 30},
            },
        )

    async def scenario() -> None:
        client = _openai_client(handler)
        provider = OpenAICompatibleProvider(
            api_key="secret",
            base_url="https://api.example/v1/",
            client=client,
        )
        try:
            response = await provider.complete(
                CompletionRequest(
                    messages=[Message(role=Role.USER, content="hello")],
                    model="gpt-4.1-mini",
                    tools=[_tool("calculator")],
                )
            )
        finally:
            await client.aclose()
        assert response.content == "Grounded answer [1]."
        assert response.model == "gpt-4.1-mini-2026"
        assert response.usage.prompt_tokens == 120
        assert response.usage.completion_tokens == 30
        assert response.finish_reason == "stop"
        assert captured["url"] == "https://api.example/v1/chat/completions"
        assert captured["headers"]["authorization"] == "Bearer secret"
        assert captured["json"]["tool_choice"] == "auto"
        assert captured["json"]["tools"][0]["function"]["name"] == "calculator"

    asyncio.run(scenario())


def test_openai_tool_calls_and_list_content() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": [{"text": "Calling "}, {"text": "a tool."}],
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "function": {
                                        "name": "calculator",
                                        "arguments": '{"expression": "1+1"}',
                                    },
                                },
                                {
                                    "id": "call_2",
                                    "function": {"name": "lookup", "arguments": "not-json"},
                                },
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ],
                "usage": {},
            },
        )

    async def scenario() -> None:
        client = _openai_client(handler)
        provider = OpenAICompatibleProvider(
            api_key="secret", base_url="https://api.example", client=client
        )
        try:
            response = await provider.complete(
                CompletionRequest(
                    messages=[Message(role=Role.USER, content="go")], model="gpt-4.1-mini"
                )
            )
        finally:
            await client.aclose()
        assert response.content == "Calling a tool."
        assert response.tool_calls[0].arguments == {"expression": "1+1"}
        assert response.tool_calls[1].arguments == {}
        assert response.finish_reason == "tool_calls"

    asyncio.run(scenario())


@pytest.mark.parametrize("status_code", [400, 429, 500])
def test_openai_http_errors_become_provider_errors(status_code: int) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json={"error": "nope"})

    async def scenario() -> None:
        client = _openai_client(handler)
        provider = OpenAICompatibleProvider(
            api_key="secret", base_url="https://api.example", client=client
        )
        try:
            with pytest.raises(ProviderError) as excinfo:
                await provider.complete(
                    CompletionRequest(
                        messages=[Message(role=Role.USER, content="go")], model="gpt-4.1-mini"
                    )
                )
        finally:
            await client.aclose()
        assert excinfo.value.retryable is (status_code == 429 or status_code >= 500)
        assert excinfo.value.details["status_code"] == status_code

    asyncio.run(scenario())


def test_openai_transport_error_is_retryable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline")

    async def scenario() -> None:
        client = _openai_client(handler)
        provider = OpenAICompatibleProvider(
            api_key="secret", base_url="https://api.example", client=client
        )
        try:
            with pytest.raises(ProviderError) as excinfo:
                await provider.complete(
                    CompletionRequest(
                        messages=[Message(role=Role.USER, content="go")], model="gpt-4.1-mini"
                    )
                )
        finally:
            await client.aclose()
        assert excinfo.value.retryable is True
        assert "transport failure" in excinfo.value.message

    asyncio.run(scenario())


def test_openai_unexpected_payload() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": []})

    async def scenario() -> None:
        client = _openai_client(handler)
        provider = OpenAICompatibleProvider(
            api_key="secret", base_url="https://api.example", client=client
        )
        try:
            with pytest.raises(ProviderError, match="unexpected payload"):
                await provider.complete(
                    CompletionRequest(
                        messages=[Message(role=Role.USER, content="go")], model="gpt-4.1-mini"
                    )
                )
        finally:
            await client.aclose()

    asyncio.run(scenario())


def test_openai_azure_style_headers_and_model_map() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["json"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]},
        )

    async def scenario() -> None:
        client = _openai_client(handler)
        provider = OpenAICompatibleProvider(
            api_key="azure-key",
            base_url="https://resource.openai.azure.com/openai/deployments/gpt-4o",
            name="azure-openai",
            client=client,
            extra_headers={"api-key": "azure-key"},
            path="/chat/completions?api-version=2024-10-21",
            model_map={"azure-gpt-4o": "gpt-4o"},
        )
        try:
            assert provider.available() is True
            await provider.complete(
                CompletionRequest(
                    messages=[Message(role=Role.USER, content="go")], model="azure-gpt-4o"
                )
            )
        finally:
            await client.aclose()
        assert captured["url"].endswith("?api-version=2024-10-21")
        assert captured["headers"]["api-key"] == "azure-key"
        assert "authorization" not in captured["headers"]
        assert captured["json"]["model"] == "gpt-4o"

    asyncio.run(scenario())


def test_openai_unavailable_without_credentials() -> None:
    assert OpenAICompatibleProvider(api_key="", base_url="").available() is False


# -- Anthropic --------------------------------------------------------------


def test_anthropic_payload_and_response() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["headers"] = dict(request.headers)
        captured["json"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "model": "claude-sonnet-4-5",
                "content": [
                    {"type": "text", "text": "Answer [1]."},
                    {"type": "tool_use", "id": "toolu_1", "name": "calculator", "input": {"x": 1}},
                ],
                "stop_reason": "tool_use",
                "usage": {"input_tokens": 50, "output_tokens": 10},
            },
        )

    call = ToolCall(id="toolu_0", name="calculator", arguments={"expression": "1+1"})
    messages = [
        Message(role=Role.SYSTEM, content="Rules one."),
        Message(role=Role.SYSTEM, content="Rules two."),
        Message(role=Role.USER, content="Calculate."),
        Message(role=Role.ASSISTANT, content="Working.", tool_calls=[call]),
        Message(role=Role.TOOL, name="calculator", tool_call_id=call.id, content="2"),
        Message(role=Role.TOOL, name="calculator", tool_call_id=call.id, content="2"),
    ]

    async def scenario() -> None:
        client = _openai_client(handler)
        provider = AnthropicProvider(api_key="anthropic-key", client=client)
        try:
            assert provider.available() is True
            response = await provider.complete(
                CompletionRequest(
                    messages=messages,
                    model="claude-sonnet-4-5",
                    tools=[_tool("calculator")],
                )
            )
        finally:
            await client.aclose()
        assert response.content == "Answer [1]."
        assert response.tool_calls[0].name == "calculator"
        assert response.tool_calls[0].arguments == {"x": 1}
        assert response.usage.prompt_tokens == 50
        assert response.usage.completion_tokens == 10
        assert response.finish_reason == "tool_use"

    asyncio.run(scenario())
    payload = captured["json"]
    assert payload["system"] == "Rules one.\n\nRules two."
    assert payload["tools"][0]["input_schema"]["type"] == "object"
    assert payload["messages"][1]["role"] == "assistant"
    assert payload["messages"][1]["content"][1]["type"] == "tool_use"
    # Consecutive tool results are merged into one user turn.
    assert len(payload["messages"]) == 3
    assert len(payload["messages"][2]["content"]) == 2
    assert captured["headers"]["x-api-key"] == "anthropic-key"


def test_anthropic_http_and_transport_errors() -> None:
    def http_error(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    def transport_error(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timeout")

    async def scenario(handler) -> None:
        client = _openai_client(handler)
        provider = AnthropicProvider(api_key="key", client=client)
        try:
            with pytest.raises(ProviderError) as excinfo:
                await provider.complete(
                    CompletionRequest(
                        messages=[Message(role=Role.USER, content="go")],
                        model="claude-sonnet-4-5",
                    )
                )
        finally:
            await client.aclose()
        assert excinfo.value.retryable is True

    asyncio.run(scenario(http_error))
    asyncio.run(scenario(transport_error))


def test_anthropic_unavailable_without_key() -> None:
    assert AnthropicProvider(api_key="").available() is False
