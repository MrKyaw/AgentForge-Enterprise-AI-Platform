"""Model gateway routing, caching, retries, fallback, limits, and budgets."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence

import pytest

from agentforge.cache import TTLCache
from agentforge.config import Settings
from agentforge.cost import BudgetGuard
from agentforge.db import Database
from agentforge.errors import BudgetExceededError, ProviderError, RateLimitError
from agentforge.gateway.base import CompletionRequest, ModelProvider, ProviderResponse
from agentforge.gateway.gateway import ModelGateway, ProviderRegistry
from agentforge.gateway.pricing import PricingCatalog
from agentforge.metrics import Metrics
from agentforge.models import Message, Role, TokenUsage, ToolSchema
from agentforge.ratelimit import TenantRateLimiter
from agentforge.usage import UsageStore


class FakeProvider(ModelProvider):
    def __init__(
        self,
        name: str,
        outcomes: Sequence[ProviderResponse | Exception] | None = None,
        *,
        available: bool = True,
    ) -> None:
        self.name = name
        self.outcomes = list(outcomes or [])
        self.available_flag = available
        self.requests: list[CompletionRequest] = []

    def available(self) -> bool:
        return self.available_flag

    async def complete(self, request: CompletionRequest) -> ProviderResponse:
        self.requests.append(request)
        if self.outcomes:
            outcome = self.outcomes.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome
        return ProviderResponse(
            content="default answer",
            model=request.model,
            provider=self.name,
            usage=TokenUsage(prompt_tokens=10, completion_tokens=5),
        )


def _response(provider: str = "local", content: str = "answer") -> ProviderResponse:
    return ProviderResponse(
        content=content,
        model="local-grounded",
        provider=provider,
        usage=TokenUsage(prompt_tokens=100, completion_tokens=25),
    )


def _gateway(
    providers: Sequence[ModelProvider],
    *,
    budget: float = 25.0,
    burst: int = 30,
    per_minute: float = 120.0,
) -> tuple[ModelGateway, Database, UsageStore]:
    settings = Settings.load(
        env={},
        model_retry_attempts=2,
        model_retry_backoff_seconds=0.0,
        request_timeout_seconds=5.0,
    )
    db = Database(":memory:")
    usage = UsageStore(db)
    gateway = ModelGateway(
        settings=settings,
        providers=ProviderRegistry(providers),
        pricing=PricingCatalog(),
        usage=usage,
        metrics=Metrics(),
        cache=TTLCache(max_entries=16, ttl_seconds=60),
        limiter=TenantRateLimiter(per_minute=per_minute, burst=burst),
        budget=BudgetGuard(usage, budget),
    )
    return gateway, db, usage


def _messages(text: str = "hello") -> list[Message]:
    return [Message(role=Role.USER, content=text)]


def _complete(gateway: ModelGateway, *, tenant: str = "demo", **kwargs):
    return asyncio.run(
        gateway.complete(
            messages=kwargs.pop("messages", _messages()),
            model=kwargs.pop("model", "local-grounded"),
            tenant=tenant,
            **kwargs,
        )
    )


def test_successful_completion_records_usage() -> None:
    provider = FakeProvider("local", [_response(content="hello")])
    gateway, db, usage = _gateway([provider])
    try:
        result = _complete(gateway)
        assert result.response.content == "hello"
        assert result.model_info.id == "local-grounded"
        assert result.attempts == 1
        assert result.fallback_used is False
        assert result.cached is False
        assert result.cost_usd == 0.0
        assert result.latency_ms >= 0
        assert provider.requests[0].model == "local-grounded"
        assert len(usage.recent("demo")) == 1
        assert usage.recent("demo")[0]["agent"] == "unknown"
    finally:
        db.close()


def test_paid_model_cost_is_calculated() -> None:
    provider = FakeProvider(
        "openai",
        [
            ProviderResponse(
                content="paid answer",
                model="gpt-4.1-mini",
                provider="openai",
                usage=TokenUsage(prompt_tokens=1000, completion_tokens=1000),
            )
        ],
    )
    gateway, db, usage = _gateway([provider])
    try:
        result = _complete(gateway, model="gpt-4.1-mini")
        assert result.model_info.id == "gpt-4.1-mini"
        assert result.cost_usd == pytest.approx(0.002)
        assert usage.spend_today("demo") == pytest.approx(0.002)
    finally:
        db.close()


def test_cache_hit_avoids_provider_call() -> None:
    provider = FakeProvider("local", [_response(content="cached answer")])
    gateway, db, usage = _gateway([provider])
    try:
        first = _complete(gateway)
        second = _complete(gateway)
        assert first.cached is False
        assert second.cached is True
        assert second.attempts == 0
        assert second.response.content == "cached answer"
        assert len(provider.requests) == 1
        entries = usage.recent("demo")
        assert len(entries) == 2
        assert sum(entry["cached"] for entry in entries) == 1
    finally:
        db.close()


def test_cache_is_scoped_to_tenant_and_disabled_for_tools() -> None:
    provider = FakeProvider("local")
    gateway, db, _ = _gateway([provider])
    try:
        _complete(gateway, tenant="demo")
        _complete(gateway, tenant="research")
        assert len(provider.requests) == 2

        tool = ToolSchema(name="calculator", description="calc")
        _complete(gateway, tools=[tool])
        _complete(gateway, tools=[tool])
        assert len(provider.requests) == 4
    finally:
        db.close()


def test_fallback_to_next_provider() -> None:
    openai = FakeProvider("openai", [ProviderError("boom", retryable=False)], available=True)
    local = FakeProvider("local", [_response(content="fallback")])
    gateway, db, _ = _gateway([openai, local])
    try:
        result = _complete(gateway, model="fast")
        assert result.fallback_used is True
        assert result.model_info.id == "local-grounded"
        assert result.attempts == 2
        assert len(openai.requests) == 1
        assert len(local.requests) == 1
    finally:
        db.close()


def test_retryable_error_is_retried() -> None:
    provider = FakeProvider(
        "openai",
        [ProviderError("temporary", retryable=True), _response("openai", "recovered")],
    )
    gateway, db, _ = _gateway([provider])
    try:
        result = _complete(gateway, model="gpt-4.1-mini")
        assert result.response.content == "recovered"
        assert result.attempts == 2
        assert result.fallback_used is False
        assert len(provider.requests) == 2
    finally:
        db.close()


def test_all_providers_failing_raises_with_attempt_details() -> None:
    openai = FakeProvider(
        "openai",
        [
            ProviderError("one", retryable=True),
            ProviderError("two", retryable=True),
        ],
    )
    local = FakeProvider("local", [ProviderError("three", retryable=False)])
    gateway, db, _ = _gateway([openai, local])
    try:
        with pytest.raises(ProviderError, match="All model providers") as excinfo:
            _complete(gateway, model="fast")
        assert excinfo.value.details["attempts"] == 3
        assert len(excinfo.value.details["errors"]) == 3
        assert excinfo.value.retryable is False
    finally:
        db.close()


def test_non_retryable_error_stops_immediately() -> None:
    provider = FakeProvider("openai", [ProviderError("bad", retryable=False)])
    gateway, db, _ = _gateway([provider])
    try:
        with pytest.raises(ProviderError, match="All model providers"):
            _complete(gateway, model="gpt-4.1-mini")
        assert len(provider.requests) == 1
    finally:
        db.close()


def test_rate_limit_is_enforced() -> None:
    provider = FakeProvider("local")
    gateway, db, _ = _gateway([provider], burst=1, per_minute=0.001)
    try:
        _complete(gateway, cacheable=False)
        with pytest.raises(RateLimitError) as excinfo:
            _complete(gateway, cacheable=False)
        assert excinfo.value.details["retry_after_seconds"] > 0
    finally:
        db.close()


def test_budget_is_enforced_before_calling_the_provider() -> None:
    provider = FakeProvider("openai")
    gateway, db, _ = _gateway([provider], budget=0.0)
    try:
        with pytest.raises(BudgetExceededError):
            _complete(gateway, model="gpt-4.1-mini")
        assert provider.requests == []
    finally:
        db.close()


def test_residency_filter_limits_candidates() -> None:
    provider = FakeProvider("local")
    gateway, db, _ = _gateway([provider])
    try:
        result = _complete(gateway, model="balanced", allowed_residencies={"local"})
        assert result.model_info.id == "local-grounded"
    finally:
        db.close()


def test_no_available_provider_for_model() -> None:
    gateway, db, _ = _gateway([FakeProvider("local")])
    try:
        with pytest.raises(ProviderError, match="No configured provider") as excinfo:
            _complete(gateway, model="gpt-4.1")
        assert excinfo.value.details["requested_model"] == "gpt-4.1"
    finally:
        db.close()


def test_unavailable_provider_is_not_selected() -> None:
    gateway, db, _ = _gateway([FakeProvider("local", available=False)])
    try:
        with pytest.raises(ProviderError, match="No configured provider"):
            _complete(gateway)
    finally:
        db.close()


def test_provider_registry_from_settings() -> None:
    offline = ProviderRegistry.from_settings(Settings.load(env={}))
    assert offline.available() == {"local"}
    assert offline.get("local") is not None
    assert offline.get("openai") is None

    configured = ProviderRegistry.from_settings(
        Settings.load(
            env={
                "OPENAI_API_KEY": "openai-key",
                "ANTHROPIC_API_KEY": "anthropic-key",
                "AZURE_OPENAI_ENDPOINT": "https://resource.openai.azure.com",
                "AZURE_OPENAI_API_KEY": "azure-key",
            }
        )
    )
    assert configured.available() == {"local", "openai", "anthropic", "azure-openai"}
    assert set(configured.all()) == {"local", "openai", "anthropic", "azure-openai"}
    asyncio.run(configured.aclose())


def test_cache_key_varies_by_tenant_and_messages() -> None:
    first = ModelGateway._cache_key(_messages("a"), "model", "demo", 0.0, 100)
    second = ModelGateway._cache_key(_messages("a"), "model", "research", 0.0, 100)
    third = ModelGateway._cache_key(_messages("b"), "model", "demo", 0.0, 100)
    assert len({first, second, third}) == 3
    assert first.startswith("completion:")
