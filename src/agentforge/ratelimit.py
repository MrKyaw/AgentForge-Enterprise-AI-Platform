"""Per-tenant token-bucket rate limiting."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(slots=True)
class RateDecision:
    allowed: bool
    remaining: float
    retry_after: float = 0.0


@dataclass(slots=True)
class _Bucket:
    tokens: float
    updated_at: float


class TenantRateLimiter:
    """Token bucket refilled continuously at ``per_minute / 60`` tokens/second."""

    def __init__(
        self,
        per_minute: float = 120.0,
        burst: int = 30,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if per_minute <= 0:
            raise ValueError("per_minute must be > 0")
        if burst < 1:
            raise ValueError("burst must be >= 1")
        self.rate_per_second = per_minute / 60.0
        self.capacity = float(burst)
        self._clock = clock
        self._buckets: dict[str, _Bucket] = {}
        self._lock = threading.Lock()

    def consume(self, key: str, tokens: float = 1.0) -> RateDecision:
        if tokens <= 0:
            raise ValueError("tokens must be > 0")
        now = self._clock()
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                bucket = _Bucket(tokens=self.capacity, updated_at=now)
                self._buckets[key] = bucket
            elapsed = max(0.0, now - bucket.updated_at)
            bucket.tokens = min(self.capacity, bucket.tokens + elapsed * self.rate_per_second)
            bucket.updated_at = now
            if bucket.tokens >= tokens:
                bucket.tokens -= tokens
                return RateDecision(
                    allowed=True,
                    remaining=round(bucket.tokens, 3),
                )
            deficit = tokens - bucket.tokens
            retry_after = deficit / self.rate_per_second
            return RateDecision(
                allowed=False,
                remaining=round(bucket.tokens, 3),
                retry_after=round(retry_after, 3),
            )

    def reset(self) -> None:
        with self._lock:
            self._buckets.clear()
