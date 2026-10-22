"""Per-tenant token bucket behavior."""

from __future__ import annotations

import pytest

from agentforge.ratelimit import TenantRateLimiter


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def test_burst_then_denial() -> None:
    limiter = TenantRateLimiter(per_minute=60, burst=2)
    assert limiter.consume("demo").allowed is True
    assert limiter.consume("demo").allowed is True
    denied = limiter.consume("demo")
    assert denied.allowed is False
    assert denied.remaining == 0
    assert denied.retry_after > 0


def test_tokens_refill_at_configured_rate() -> None:
    clock = FakeClock()
    limiter = TenantRateLimiter(per_minute=60, burst=1, clock=clock)
    assert limiter.consume("demo").allowed is True
    assert limiter.consume("demo").allowed is False
    clock.advance(1.0)  # 60/min => 1 token per second
    assert limiter.consume("demo").allowed is True


def test_buckets_are_isolated_per_tenant() -> None:
    limiter = TenantRateLimiter(per_minute=60, burst=1)
    assert limiter.consume("a").allowed is True
    assert limiter.consume("a").allowed is False
    assert limiter.consume("b").allowed is True


def test_reset_restores_capacity() -> None:
    limiter = TenantRateLimiter(per_minute=60, burst=1)
    limiter.consume("a")
    assert limiter.consume("a").allowed is False
    limiter.reset()
    assert limiter.consume("a").allowed is True


def test_token_argument_validation() -> None:
    limiter = TenantRateLimiter(per_minute=60, burst=2)
    with pytest.raises(ValueError, match="tokens"):
        limiter.consume("a", 0)
    assert limiter.consume("a", 1.5).allowed is True


def test_invalid_configuration() -> None:
    with pytest.raises(ValueError, match="per_minute"):
        TenantRateLimiter(per_minute=0)
    with pytest.raises(ValueError, match="burst"):
        TenantRateLimiter(burst=0)
