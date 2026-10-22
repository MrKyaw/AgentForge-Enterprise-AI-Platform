"""Dependency-free Prometheus metrics with labels and histograms."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from time import perf_counter

BUCKETS: tuple[float, ...] = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)


def _label_string(labels: dict[str, str]) -> str:
    if not labels:
        return ""
    parts = []
    for key in sorted(labels):
        value = str(labels[key]).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")
        parts.append(f'{key}="{value}"')
    return "{" + ",".join(parts) + "}"


def _key(name: str, labels: dict[str, str]) -> tuple[str, tuple[tuple[str, str], ...]]:
    return name, tuple(sorted((str(k), str(v)) for k, v in labels.items()))


class _Histogram:
    __slots__ = ("buckets", "count", "sum")

    def __init__(self) -> None:
        self.buckets = dict.fromkeys(BUCKETS, 0)
        self.count = 0
        self.sum = 0.0


class Metrics:
    """Thread-safe counters, gauges, and histograms rendered in Prometheus format."""

    def __init__(self) -> None:
        self._counters: dict[tuple[str, tuple[tuple[str, str], ...]], float] = {}
        self._gauges: dict[tuple[str, tuple[tuple[str, str], ...]], float] = {}
        self._histograms: dict[tuple[str, tuple[tuple[str, str], ...]], _Histogram] = {}
        self._lock = threading.Lock()

    def inc(self, name: str, value: float = 1.0, **labels: str) -> None:
        key = _key(name, labels)
        with self._lock:
            self._counters[key] = self._counters.get(key, 0.0) + value

    def set_gauge(self, name: str, value: float, **labels: str) -> None:
        key = _key(name, labels)
        with self._lock:
            self._gauges[key] = value

    def observe(self, name: str, value: float, **labels: str) -> None:
        key = _key(name, labels)
        with self._lock:
            observation = self._histograms.setdefault(key, _Histogram())
            observation.count += 1
            observation.sum += value
            for boundary in BUCKETS:
                if value <= boundary:
                    observation.buckets[boundary] += 1

    @contextmanager
    def time(self, name: str, **labels: str) -> Iterator[None]:
        started = perf_counter()
        try:
            yield
        finally:
            self.observe(name, perf_counter() - started, **labels)

    def counter_value(self, name: str, **labels: str) -> float:
        key = _key(name, labels)
        with self._lock:
            return self._counters.get(key, 0.0)

    def histogram_count(self, name: str, **labels: str) -> int:
        key = _key(name, labels)
        with self._lock:
            observation = self._histograms.get(key)
            return observation.count if observation else 0

    def render(self) -> str:
        lines: list[str] = []
        with self._lock:
            for (name, labels), value in sorted(self._counters.items()):
                label_text = _label_string(dict(labels))
                lines.append(f"{name}{label_text} {value:g}")
            for (name, labels), value in sorted(self._gauges.items()):
                label_text = _label_string(dict(labels))
                lines.append(f"{name}{label_text} {value:g}")
            for (name, labels), observation in sorted(self._histograms.items()):
                label_dict = dict(labels)
                for boundary in BUCKETS:
                    bucket_labels = dict(label_dict, le=str(boundary))
                    lines.append(
                        f"{name}_bucket{_label_string(bucket_labels)} "
                        f"{observation.buckets[boundary]}"
                    )
                lines.append(
                    f"{name}_bucket{_label_string(dict(label_dict, le='+Inf'))} {observation.count}"
                )
                lines.append(f"{name}_sum{_label_string(label_dict)} {observation.sum:g}")
                lines.append(f"{name}_count{_label_string(label_dict)} {observation.count}")
        return "\n".join(lines) + ("\n" if lines else "")

    def reset(self) -> None:
        with self._lock:
            self._counters.clear()
            self._gauges.clear()
            self._histograms.clear()
