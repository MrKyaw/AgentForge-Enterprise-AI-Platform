"""Resilient model gateway with fallback, caching, rate limits, and cost control."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from hashlib import sha256
from time import perf_counter
from typing import Any

import httpx

from agentforge.cache import TTLCache
from agentforge.config import Settings
from agentforge.cost import BudgetGuard
from agentforge.errors import ProviderError, RateLimitError
from agentforge.gateway.base import CompletionRequest, ModelProvider, ProviderResponse
from agentforge.gateway.pricing import ModelInfo, PricingCatalog
from agentforge.gateway.providers import (
    AnthropicProvider,
    LocalGroundedProvider,
    OpenAICompatibleProvider,
)
from agentforge.metrics import Metrics
from agentforge.models import Message, TokenUsage, ToolSchema
from agentforge.ratelimit import TenantRateLimiter
from agentforge.usage import UsageStore
from agentforge.util import canonical_json, estimate_tokens


@dataclass(slots=True)
class GatewayResult:
    response: ProviderResponse
    model_info: ModelInfo
    cost_usd: float
    cached: bool
    latency_ms: float
    attempts: int
    fallback_used: bool


@dataclass(slots=True)
class _CachedResponse:
    content: str
    model_id: str
    provider: str
    usage: TokenUsage


class ProviderRegistry:
    def __init__(self, providers: Sequence[ModelProvider]) -> None:
        self._providers = {provider.name: provider for provider in providers}

    @classmethod
    def from_settings(
        cls,
        settings: Settings,
        clients: dict[str, httpx.AsyncClient] | None = None,
    ) -> ProviderRegistry:
        clients = clients or {}
        providers: list[ModelProvider] = [LocalGroundedProvider()]
        if settings.openai_api_key:
            providers.append(
                OpenAICompatibleProvider(
                    api_key=settings.openai_api_key,
                    base_url=settings.openai_base_url,
                    name="openai",
                    timeout_seconds=settings.request_timeout_seconds,
                    client=clients.get("openai"),
                )
            )
        if settings.anthropic_api_key:
            providers.append(
                AnthropicProvider(
                    api_key=settings.anthropic_api_key,
                    timeout_seconds=settings.request_timeout_seconds,
                    client=clients.get("anthropic"),
                )
            )
        if settings.azure_openai_endpoint and settings.azure_openai_api_key:
            deployment = settings.azure_openai_deployment
            providers.append(
                OpenAICompatibleProvider(
                    api_key=settings.azure_openai_api_key,
                    base_url=(
                        f"{settings.azure_openai_endpoint.rstrip('/')}"
                        f"/openai/deployments/{deployment}"
                    ),
                    name="azure-openai",
                    timeout_seconds=settings.request_timeout_seconds,
                    client=clients.get("azure-openai"),
                    extra_headers={"api-key": settings.azure_openai_api_key},
                    path=(f"/chat/completions?api-version={settings.azure_openai_api_version}"),
                    model_map={"azure-gpt-4o": deployment},
                )
            )
        return cls(providers)

    def get(self, name: str) -> ModelProvider | None:
        provider = self._providers.get(name)
        if provider is None or not provider.available():
            return None
        return provider

    def available(self) -> set[str]:
        return {name for name, provider in self._providers.items() if provider.available()}

    def all(self) -> dict[str, ModelProvider]:
        return dict(self._providers)

    async def aclose(self) -> None:
        for provider in self._providers.values():
            await provider.aclose()


class ModelGateway:
    def __init__(
        self,
        *,
        settings: Settings,
        providers: ProviderRegistry,
        pricing: PricingCatalog,
        usage: UsageStore,
        metrics: Metrics,
        cache: TTLCache[_CachedResponse],
        limiter: TenantRateLimiter,
        budget: BudgetGuard,
    ) -> None:
        self.settings = settings
        self.providers = providers
        self.pricing = pricing
        self.usage = usage
        self.metrics = metrics
        self.cache = cache
        self.limiter = limiter
        self.budget = budget

    async def complete(
        self,
        *,
        messages: Sequence[Message],
        model: str,
        tenant: str,
        agent: str = "unknown",
        run_id: str = "",
        temperature: float = 0.0,
        max_tokens: int = 900,
        tools: Sequence[ToolSchema] | None = None,
        cacheable: bool = True,
        allowed_residencies: set[str] | None = None,
    ) -> GatewayResult:
        started = perf_counter()
        decision = self.limiter.consume(f"model:{tenant}")
        if not decision.allowed:
            self.metrics.inc("agentforge_rate_limited_total", tenant=tenant)
            raise RateLimitError(
                "Model request rate limit exceeded for this tenant.",
                retry_after=decision.retry_after,
            )

        tools = list(tools or [])
        candidates = [
            info
            for info in self.pricing.resolve(model)
            if self.providers.get(info.provider) is not None
        ]
        if allowed_residencies:
            candidates = [
                info
                for info in candidates
                if info.residency in allowed_residencies or info.residency == "local"
            ]
        if not candidates:
            raise ProviderError(
                "No configured provider is available for the requested model.",
                details={
                    "requested_model": model,
                    "available_providers": sorted(self.providers.available()),
                },
            )

        use_cache = cacheable and not tools
        cache_key = self._cache_key(messages, model, tenant, temperature, max_tokens)
        if use_cache:
            cached = self.cache.get(cache_key)
            if cached is not None:
                info = self.pricing.get(cached.model_id) or candidates[0]
                latency_ms = (perf_counter() - started) * 1000
                self.usage.record(
                    tenant=tenant,
                    agent=agent,
                    model=info.id,
                    usage=cached.usage,
                    cost_usd=0.0,
                    cached=True,
                    latency_ms=latency_ms,
                    run_id=run_id,
                )
                self.metrics.inc(
                    "agentforge_model_requests_total",
                    model=info.id,
                    provider=info.provider,
                    status="success",
                    cached="true",
                )
                self.metrics.observe(
                    "agentforge_model_latency_seconds", latency_ms / 1000, model=info.id
                )
                return GatewayResult(
                    response=ProviderResponse(
                        content=cached.content,
                        model=info.id,
                        provider=cached.provider,
                        usage=cached.usage,
                    ),
                    model_info=info,
                    cost_usd=0.0,
                    cached=True,
                    latency_ms=latency_ms,
                    attempts=0,
                    fallback_used=False,
                )

        prompt_estimate = sum(
            estimate_tokens(message.content)
            + sum(estimate_tokens(call.name) for call in message.tool_calls)
            for message in messages
        )
        projected_cost = self.pricing.calculate(candidates[0].id, prompt_estimate, max_tokens)
        self.budget.check(tenant, projected_cost)

        attempts = 0
        errors: list[dict[str, Any]] = []
        last_error: ProviderError | None = None
        for candidate_index, info in enumerate(candidates):
            provider = self.providers.get(info.provider)
            if provider is None:  # pragma: no cover - defensive
                continue
            for attempt in range(max(1, self.settings.model_retry_attempts)):
                attempts += 1
                try:
                    response = await provider.complete(
                        CompletionRequest(
                            messages=list(messages),
                            model=info.id,
                            temperature=temperature,
                            max_tokens=max_tokens,
                            tools=tools,
                            timeout_seconds=self.settings.request_timeout_seconds,
                        )
                    )
                    usage = TokenUsage(
                        prompt_tokens=response.usage.prompt_tokens or prompt_estimate,
                        completion_tokens=response.usage.completion_tokens
                        or (0 if response.tool_calls else estimate_tokens(response.content)),
                    )
                    response.usage = usage
                    cost = self.pricing.calculate(
                        info.id, usage.prompt_tokens, usage.completion_tokens
                    )
                    latency_ms = (perf_counter() - started) * 1000
                    self.usage.record(
                        tenant=tenant,
                        agent=agent,
                        model=info.id,
                        usage=usage,
                        cost_usd=cost,
                        cached=False,
                        latency_ms=latency_ms,
                        run_id=run_id,
                    )
                    self.metrics.inc(
                        "agentforge_model_requests_total",
                        model=info.id,
                        provider=info.provider,
                        status="success",
                        cached="false",
                    )
                    self.metrics.observe(
                        "agentforge_model_latency_seconds", latency_ms / 1000, model=info.id
                    )
                    self.metrics.inc(
                        "agentforge_tokens_total", usage.prompt_tokens, model=info.id, kind="prompt"
                    )
                    self.metrics.inc(
                        "agentforge_tokens_total",
                        usage.completion_tokens,
                        model=info.id,
                        kind="completion",
                    )
                    if cost:
                        self.metrics.inc("agentforge_model_cost_usd_total", cost, model=info.id)
                    if use_cache and not response.tool_calls and response.content:
                        self.cache.set(
                            cache_key,
                            _CachedResponse(
                                content=response.content,
                                model_id=info.id,
                                provider=response.provider,
                                usage=usage,
                            ),
                        )
                    return GatewayResult(
                        response=response,
                        model_info=info,
                        cost_usd=cost,
                        cached=False,
                        latency_ms=latency_ms,
                        attempts=attempts,
                        fallback_used=candidate_index > 0,
                    )
                except ProviderError as exc:
                    last_error = exc
                    errors.append(
                        {
                            "model": info.id,
                            "provider": info.provider,
                            "attempt": attempts,
                            "retryable": exc.retryable,
                            "message": exc.message,
                        }
                    )
                    if not exc.retryable:
                        break
                    if attempt + 1 < max(1, self.settings.model_retry_attempts):
                        backoff = self.settings.model_retry_backoff_seconds * (2**attempt)
                        if backoff > 0:
                            await asyncio.sleep(backoff)
            self.metrics.inc(
                "agentforge_model_requests_total",
                model=info.id,
                provider=info.provider,
                status="error",
                cached="false",
            )
        self.metrics.inc(
            "agentforge_model_requests_total",
            model=model,
            provider="none",
            status="failed",
            cached="false",
        )
        raise ProviderError(
            "All model providers in the fallback chain failed.",
            retryable=bool(last_error and last_error.retryable),
            details={"attempts": attempts, "errors": errors},
        )

    @staticmethod
    def _cache_key(
        messages: Sequence[Message],
        model: str,
        tenant: str,
        temperature: float,
        max_tokens: int,
    ) -> str:
        digest = sha256(
            canonical_json(
                {
                    "model": model,
                    "tenant": tenant,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                    "messages": [message.model_dump(mode="json") for message in messages],
                }
            ).encode()
        ).hexdigest()
        return f"completion:{digest}"
