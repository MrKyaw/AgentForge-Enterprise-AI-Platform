"""TTL + LRU cache behavior is deterministic under an injected clock."""

from __future__ import annotations

import pytest

from agentforge.cache import TTLCache


class FakeClock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def test_get_set_and_stats() -> None:
    cache: TTLCache[str] = TTLCache(max_entries=3, ttl_seconds=10)
    assert cache.get("missing") is None
    cache.set("a", "alpha")
    assert cache.get("a") == "alpha"
    assert len(cache) == 1
    stats = cache.stats()
    assert stats["hits"] == 1
    assert stats["misses"] == 1
    assert stats["entries"] == 1


def test_entries_expire() -> None:
    clock = FakeClock()
    cache: TTLCache[str] = TTLCache(max_entries=3, ttl_seconds=10, clock=clock)
    cache.set("a", "alpha")
    clock.advance(9.9)
    assert cache.get("a") == "alpha"
    clock.advance(0.2)
    assert cache.get("a") is None
    assert len(cache) == 0


def test_per_entry_ttl_override() -> None:
    clock = FakeClock()
    cache: TTLCache[str] = TTLCache(max_entries=3, ttl_seconds=100, clock=clock)
    cache.set("short", "value", ttl_seconds=1)
    clock.advance(2)
    assert cache.get("short") is None


def test_lru_eviction() -> None:
    cache: TTLCache[int] = TTLCache(max_entries=2, ttl_seconds=100)
    cache.set("a", 1)
    cache.set("b", 2)
    assert cache.get("a") == 1  # touch a so b becomes oldest
    cache.set("c", 3)
    assert cache.get("b") is None
    assert cache.get("a") == 1
    assert cache.get("c") == 3
    assert cache.stats()["evictions"] == 1


def test_reset_and_delete() -> None:
    cache: TTLCache[int] = TTLCache(max_entries=2, ttl_seconds=100)
    cache.set("a", 1)
    cache.delete("a")
    cache.delete("missing")
    assert len(cache) == 0
    cache.set("b", 2)
    cache.clear()
    assert len(cache) == 0


def test_invalid_configuration() -> None:
    with pytest.raises(ValueError, match="max_entries"):
        TTLCache(max_entries=0)
    with pytest.raises(ValueError, match="ttl_seconds"):
        TTLCache(ttl_seconds=0)
