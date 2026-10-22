"""Lightweight in-process distributed-trace model.

The interface mirrors OpenTelemetry spans closely enough to swap in an OTLP
exporter without changing runtime call sites.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any

from agentforge.util import new_id, now_iso


@dataclass(slots=True)
class Span:
    id: str
    name: str
    started_at: str
    parents: list[str] = field(default_factory=list)
    attributes: dict[str, Any] = field(default_factory=dict)
    duration_ms: float = 0.0
    status: str = "ok"
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "started_at": self.started_at,
            "parents": self.parents,
            "attributes": self.attributes,
            "duration_ms": round(self.duration_ms, 3),
            "status": self.status,
            "error": self.error,
        }


@dataclass(slots=True)
class Trace:
    id: str
    name: str
    started_at: str
    attributes: dict[str, Any] = field(default_factory=dict)
    spans: list[Span] = field(default_factory=list)
    duration_ms: float = 0.0
    status: str = "ok"
    _started: float = field(default_factory=perf_counter, repr=False)
    _stack: list[Span] = field(default_factory=list, repr=False)

    @contextmanager
    def span(self, name: str, **attributes: Any) -> Iterator[Span]:
        span = Span(
            id=new_id("spn", 10),
            name=name,
            started_at=now_iso(),
            parents=[self._stack[-1].id] if self._stack else [],
            attributes=attributes,
        )
        self._stack.append(span)
        started = perf_counter()
        try:
            yield span
        except Exception as exc:
            span.status = "error"
            span.error = str(exc)
            self.status = "error"
            raise
        finally:
            span.duration_ms = (perf_counter() - started) * 1000
            self.spans.append(span)
            if self._stack and self._stack[-1] is span:
                self._stack.pop()

    def finish(self) -> None:
        self.duration_ms = (perf_counter() - self._started) * 1000

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "started_at": self.started_at,
            "attributes": self.attributes,
            "duration_ms": round(self.duration_ms, 3),
            "status": self.status,
            "spans": [span.to_dict() for span in self.spans],
        }


class Tracer:
    def __init__(self, max_traces: int = 1000) -> None:
        self.max_traces = max_traces
        self._traces: OrderedDict[str, Trace] = OrderedDict()
        self._lock = threading.Lock()

    def start_trace(self, name: str, **attributes: Any) -> Trace:
        trace = Trace(id=new_id("tr"), name=name, started_at=now_iso(), attributes=attributes)
        with self._lock:
            self._traces[trace.id] = trace
            while len(self._traces) > self.max_traces:
                self._traces.popitem(last=False)
        return trace

    def get(self, trace_id: str) -> Trace | None:
        with self._lock:
            return self._traces.get(trace_id)

    def count(self) -> int:
        with self._lock:
            return len(self._traces)
