"""Provider adapters: offline grounded, OpenAI-compatible, Azure, and Anthropic."""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from typing import Any

import httpx

from agentforge.errors import ProviderError
from agentforge.gateway.base import CompletionRequest, ModelProvider, ProviderResponse
from agentforge.models import Message, Role, TokenUsage, ToolCall
from agentforge.security import assess_injection  # noqa: F401  (documented guardrail coupling)
from agentforge.util import (
    clip,
    content_tokens,
    estimate_tokens,
    safe_json_loads,
)

_CONTEXT_LINE = re.compile(
    r"^\[(\d+)\]\s+(.+?)\s+\[([^\]]+)\]\s+::\s+(.+)$",
    re.MULTILINE,
)
_PORTFOLIO_ID = re.compile(r"\b[A-Z]{2,4}-\d{3,6}\b")
_CLIENT_ID = re.compile(r"\bCL-\d{3,6}\b")
_ARITHMETIC = re.compile(
    r"(?<![\w.])(\(?\s*-?\d[\d,]*(?:\.\d+)?"
    r"(?:\s*(?:\*\*|[+\-*/^])\s*\(?\s*-?\d[\d,]*(?:\.\d+)?\s*\)?)+)"
)
_SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")
_REFUSAL = (
    "I don't have enough grounded evidence in the approved knowledge base to answer that question."
)


def _latest_user(messages: Sequence[Message]) -> str:
    for message in reversed(messages):
        if message.role == Role.USER:
            return message.content
    return ""


def _parse_sources(system_prompt: str) -> list[tuple[int, str, str, str]]:
    sources: list[tuple[int, str, str, str]] = []
    for match in _CONTEXT_LINE.finditer(system_prompt):
        sources.append(
            (
                int(match.group(1)),
                match.group(2).strip(),
                match.group(3).strip(),
                match.group(4).strip(),
            )
        )
    return sources


def _tool_results(messages: Sequence[Message]) -> list[tuple[str, str]]:
    results: list[tuple[str, str]] = []
    for message in messages:
        if message.role == Role.TOOL:
            results.append((message.name or "tool", message.content))
    return results


def _available(messages: Sequence[Message], tool_name: str) -> bool:
    return any(call.name == tool_name for message in messages for call in message.tool_calls)


def _used(messages: Sequence[Message], tool_name: str) -> bool:
    return _available(messages, tool_name)


class LocalGroundedProvider(ModelProvider):
    """Deterministic, offline provider used for demos, tests, and air-gapped mode.

    It performs extractive synthesis over the retrieved sources and can emit
    deterministic tool calls for common operational intents. It is explicitly
    *not* a language model: it exists so the platform's control-plane behavior is
    reproducible without API keys or network access.
    """

    name = "local"
    model_id = "local-grounded"

    def available(self) -> bool:
        return True

    def _plan_tools(
        self,
        messages: Sequence[Message],
        request: CompletionRequest,
        query: str,
    ) -> list[ToolCall]:
        names = {tool.name for tool in request.tools}
        plans: list[ToolCall] = []
        lowered = query.lower()
        portfolio_id = _PORTFOLIO_ID.search(query)
        client_id = _CLIENT_ID.search(query)

        if (
            client_id
            and "lookup_client" in names
            and not _used(messages, "lookup_client")
            and ("client" in lowered or "ticket" in lowered or "complaint" in lowered)
        ):
            plans.append(
                ToolCall(name="lookup_client", arguments={"client_id": client_id.group(0)})
            )

        if (
            portfolio_id
            and "portfolio_lookup" in names
            and not _used(messages, "portfolio_lookup")
            and ("portfolio" in lowered or "holding" in lowered or "value" in lowered)
        ):
            plans.append(
                ToolCall(
                    name="portfolio_lookup",
                    arguments={"portfolio_id": portfolio_id.group(0)},
                )
            )

        expression = _ARITHMETIC.search(query)
        if expression and "calculator" in names and not _used(messages, "calculator"):
            cleaned = expression.group(1).replace(",", "").replace("^", "**").strip()
            if 1 < len(cleaned) <= 80:
                plans.append(ToolCall(name="calculator", arguments={"expression": cleaned}))

        if (
            "model_selector" in names
            and not _used(messages, "model_selector")
            and re.search(r"(which|recommend|select|choose).{0,40}model", lowered)
        ):
            plans.append(
                ToolCall(
                    name="model_selector",
                    arguments={
                        "use_case": clip(query, 240),
                        "data_residency": "local" if "local" in lowered else "global",
                        "requires_tools": True,
                    },
                )
            )

        if (
            client_id
            and "create_service_ticket" in names
            and not _used(messages, "create_service_ticket")
            and ("ticket" in lowered or "complaint" in lowered)
        ):
            plans.append(
                ToolCall(
                    name="create_service_ticket",
                    arguments={
                        "client_id": client_id.group(0),
                        "summary": clip(query, 240),
                        "priority": "high" if "urgent" in lowered else "normal",
                    },
                )
            )

        if (
            portfolio_id
            and "create_rebalance_task" in names
            and not _used(messages, "create_rebalance_task")
            and "rebalance" in lowered
        ):
            plans.append(
                ToolCall(
                    name="create_rebalance_task",
                    arguments={
                        "portfolio_id": portfolio_id.group(0),
                        "reason": clip(query, 240),
                    },
                )
            )
        return plans

    def _compose(self, system_prompt: str, query: str, messages: Sequence[Message]) -> str:
        sources = _parse_sources(system_prompt)
        tool_results = _tool_results(messages)
        tool_text = ""
        if tool_results:
            rendered = []
            for name, content in tool_results:
                data = safe_json_loads(content, content)
                if isinstance(data, dict) and data.get("ok") is False:
                    rendered.append(f"The `{name}` tool could not complete: {data.get('error')}.")
                else:
                    rendered.append(f"The `{name}` tool returned {json.dumps(data, default=str)}.")
            tool_text = " ".join(rendered)

        if not sources:
            return tool_text.strip() if tool_text else _REFUSAL

        query_terms = set(content_tokens(query))
        context_text = " ".join(content for _, _, _, content in sources)
        context_terms = set(content_tokens(context_text))
        numeric_terms = {term for term in query_terms if any(char.isdigit() for char in term)}
        missing_numbers = numeric_terms - context_terms
        coverage = len(query_terms & context_terms) / len(query_terms) if query_terms else 0.0

        if not tool_text and (coverage < 0.6 or missing_numbers):
            return _REFUSAL

        candidates: list[tuple[float, int, str, str]] = []
        for index, title, _document_id, content in sources:
            for sentence in _SENTENCE.split(content):
                raw = sentence.strip(" -•\t")
                sentence = re.sub(r"^#+\s*", "", raw)
                if len(sentence) < 18:
                    continue
                if raw.startswith("#") and len(sentence.split()) <= 4:
                    continue
                overlap = len(query_terms & set(content_tokens(sentence)))
                candidates.append((float(overlap), index, title, sentence))
        candidates.sort(key=lambda item: (item[0], -item[1]), reverse=True)

        chosen: list[tuple[int, str]] = []
        seen: set[str] = set()
        for score, index, _title, sentence in candidates:
            if score <= 0 and chosen:
                break
            signature = sentence[:80].lower()
            if signature in seen:
                continue
            seen.add(signature)
            chosen.append((index, sentence))
            if len(chosen) >= 3:
                break

        if not chosen and sources:
            for index, _title, _document_id, content in sources[:2]:
                first = _SENTENCE.split(content)[0].strip()
                if first:
                    chosen.append((index, first))

        evidence = " ".join(
            f"{sentence.rstrip('.')} [{index}]." for index, sentence in chosen
        ).strip()
        if tool_text and evidence:
            answer = f"{tool_text} Supporting policy: {evidence}"
        elif tool_text:
            answer = tool_text
        elif evidence:
            answer = f"Based on the approved knowledge base: {evidence}"
        else:
            answer = _REFUSAL
        return clip(answer, 1200)

    async def complete(self, request: CompletionRequest) -> ProviderResponse:
        query = _latest_user(request.messages)
        system_prompt = "\n".join(
            message.content for message in request.messages if message.role == Role.SYSTEM
        )
        tool_calls = self._plan_tools(request.messages, request, query)
        if tool_calls:
            return ProviderResponse(
                content="",
                model=self.model_id,
                provider=self.name,
                tool_calls=tool_calls,
                finish_reason="tool_calls",
                usage=TokenUsage(
                    prompt_tokens=sum(estimate_tokens(m.content) for m in request.messages),
                    completion_tokens=0,
                ),
            )
        answer = self._compose(system_prompt, query, request.messages)
        return ProviderResponse(
            content=answer,
            model=self.model_id,
            provider=self.name,
            finish_reason="stop",
            usage=TokenUsage(
                prompt_tokens=sum(estimate_tokens(m.content) for m in request.messages),
                completion_tokens=estimate_tokens(answer),
            ),
        )


class OpenAICompatibleProvider(ModelProvider):
    """OpenAI Chat Completions adapter, also used for Azure OpenAI deployments."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        name: str = "openai",
        timeout_seconds: float = 30.0,
        client: httpx.AsyncClient | None = None,
        extra_headers: dict[str, str] | None = None,
        path: str = "/chat/completions",
        model_map: dict[str, str] | None = None,
    ) -> None:
        self.name = name
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.extra_headers = extra_headers or {}
        self.path = path
        self.model_map = model_map or {}
        self._client = client

    def available(self) -> bool:
        return bool(self.api_key and self.base_url)

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout_seconds)
        return self._client

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json", **self.extra_headers}
        if "api-key" not in headers:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _payload(self, request: CompletionRequest) -> dict[str, Any]:
        model = self.model_map.get(request.model, request.model)
        payload: dict[str, Any] = {
            "model": model,
            "messages": [_openai_message(message) for message in request.messages],
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
        }
        if request.tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.parameters,
                    },
                }
                for tool in request.tools
            ]
            payload["tool_choice"] = "auto"
        return payload

    async def complete(self, request: CompletionRequest) -> ProviderResponse:
        url = f"{self.base_url}{self.path}"
        try:
            response = await self._http().post(
                url,
                json=self._payload(request),
                headers=self._headers(),
                timeout=request.timeout_seconds,
            )
        except httpx.HTTPError as exc:
            raise ProviderError(
                f"{self.name} transport failure: {type(exc).__name__}.",
                retryable=True,
            ) from exc
        _raise_for_status(self.name, response)
        data = response.json()
        try:
            choice = data["choices"][0]
            message = choice.get("message", {})
        except (KeyError, IndexError) as exc:
            raise ProviderError(f"{self.name} returned an unexpected payload.") from exc
        content = message.get("content") or ""
        if isinstance(content, list):
            content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
        calls: list[ToolCall] = []
        for call in message.get("tool_calls") or []:
            function = call.get("function", {})
            calls.append(
                ToolCall(
                    id=call.get("id", ""),
                    name=function.get("name", ""),
                    arguments=safe_json_loads(function.get("arguments"), {}) or {},
                )
            )
        usage = data.get("usage") or {}
        return ProviderResponse(
            content=content,
            model=data.get("model", request.model),
            provider=self.name,
            tool_calls=calls,
            finish_reason=choice.get("finish_reason", "stop"),
            usage=TokenUsage(
                prompt_tokens=int(usage.get("prompt_tokens", 0)),
                completion_tokens=int(usage.get("completion_tokens", 0)),
            ),
        )

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()


class AnthropicProvider(ModelProvider):
    """Anthropic Messages API adapter with tool-use support."""

    name = "anthropic"

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.anthropic.com/v1",
        timeout_seconds: float = 30.0,
        client: httpx.AsyncClient | None = None,
        model_map: dict[str, str] | None = None,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self._client = client
        self.model_map = model_map or {}

    def available(self) -> bool:
        return bool(self.api_key)

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout_seconds)
        return self._client

    def _payload(self, request: CompletionRequest) -> dict[str, Any]:
        system_parts: list[str] = []
        messages: list[dict[str, Any]] = []
        for message in request.messages:
            if message.role == Role.SYSTEM:
                system_parts.append(message.content)
                continue
            if message.role == Role.USER:
                messages.append({"role": "user", "content": message.content})
            elif message.role == Role.ASSISTANT:
                blocks: list[dict[str, Any]] = []
                if message.content:
                    blocks.append({"type": "text", "text": message.content})
                for call in message.tool_calls:
                    blocks.append(
                        {
                            "type": "tool_use",
                            "id": call.id,
                            "name": call.name,
                            "input": call.arguments,
                        }
                    )
                if blocks:
                    messages.append({"role": "assistant", "content": blocks})
            else:
                block = {
                    "type": "tool_result",
                    "tool_use_id": message.tool_call_id or "",
                    "content": message.content,
                }
                if (
                    messages
                    and messages[-1]["role"] == "user"
                    and isinstance(messages[-1]["content"], list)
                    and messages[-1]["content"][-1].get("type") == "tool_result"
                ):
                    messages[-1]["content"].append(block)
                else:
                    messages.append({"role": "user", "content": [block]})
        payload: dict[str, Any] = {
            "model": self.model_map.get(request.model, request.model),
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "messages": messages,
        }
        if system_parts:
            payload["system"] = "\n\n".join(system_parts)
        if request.tools:
            payload["tools"] = [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "input_schema": tool.parameters,
                }
                for tool in request.tools
            ]
        return payload

    async def complete(self, request: CompletionRequest) -> ProviderResponse:
        try:
            response = await self._http().post(
                f"{self.base_url}/messages",
                json=self._payload(request),
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                timeout=request.timeout_seconds,
            )
        except httpx.HTTPError as exc:
            raise ProviderError(
                f"anthropic transport failure: {type(exc).__name__}.",
                retryable=True,
            ) from exc
        _raise_for_status(self.name, response)
        data = response.json()
        text_parts: list[str] = []
        calls: list[ToolCall] = []
        for block in data.get("content", []):
            if block.get("type") == "text":
                text_parts.append(block.get("text", ""))
            elif block.get("type") == "tool_use":
                calls.append(
                    ToolCall(
                        id=block.get("id", ""),
                        name=block.get("name", ""),
                        arguments=block.get("input") or {},
                    )
                )
        usage = data.get("usage") or {}
        return ProviderResponse(
            content="".join(text_parts),
            model=data.get("model", request.model),
            provider=self.name,
            tool_calls=calls,
            finish_reason=data.get("stop_reason", "end_turn"),
            usage=TokenUsage(
                prompt_tokens=int(usage.get("input_tokens", 0)),
                completion_tokens=int(usage.get("output_tokens", 0)),
            ),
        )

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()


def _openai_message(message: Message) -> dict[str, Any]:
    if message.role == Role.TOOL:
        return {
            "role": "tool",
            "tool_call_id": message.tool_call_id or "",
            "content": message.content,
        }
    payload: dict[str, Any] = {
        "role": message.role.value,
        "content": message.content,
    }
    if message.tool_calls:
        payload["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {
                    "name": call.name,
                    "arguments": json.dumps(call.arguments),
                },
            }
            for call in message.tool_calls
        ]
    return payload


def _raise_for_status(provider: str, response: httpx.Response) -> None:
    if response.status_code < 400:
        return
    retryable = response.status_code in {408, 409, 425, 429} or response.status_code >= 500
    raise ProviderError(
        f"{provider} request failed with HTTP {response.status_code}.",
        retryable=retryable,
        details={"status_code": response.status_code, "provider": provider},
    )
