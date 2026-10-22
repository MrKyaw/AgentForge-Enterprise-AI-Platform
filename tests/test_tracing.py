"""Trace and span lifecycle, including error propagation."""

from __future__ import annotations

import pytest

from agentforge.tracing import Tracer


def test_nested_spans_record_parent_links() -> None:
    tracer = Tracer()
    trace = tracer.start_trace("agent.run", agent="research-copilot")
    with trace.span("retrieval") as retrieval:
        with trace.span("model.complete") as model_span:
            model_span.attributes["cached"] = False
        assert model_span.parents == [retrieval.id]
    trace.finish()

    assert trace.status == "ok"
    assert trace.duration_ms >= 0
    assert [span.name for span in trace.spans] == ["model.complete", "retrieval"]
    assert retrieval.attributes == {}
    payload = trace.to_dict()
    assert payload["name"] == "agent.run"
    assert payload["attributes"]["agent"] == "research-copilot"
    assert payload["spans"][0]["status"] == "ok"
    assert payload["spans"][0]["attributes"]["cached"] is False
    assert tracer.get(trace.id) is trace


def test_span_error_marks_trace_and_reraises() -> None:
    tracer = Tracer()
    trace = tracer.start_trace("agent.run")
    with pytest.raises(ValueError, match="bad"), trace.span("tool.invoke"):
        raise ValueError("bad")
    trace.finish()
    assert trace.status == "error"
    assert trace.spans[0].status == "error"
    assert trace.spans[0].error == "bad"


def test_tracer_bounds_stored_traces() -> None:
    tracer = Tracer(max_traces=2)
    first = tracer.start_trace("one")
    tracer.start_trace("two")
    tracer.start_trace("three")
    assert tracer.count() == 2
    assert tracer.get(first.id) is None


def test_unknown_trace_returns_none() -> None:
    assert Tracer().get("tr_missing") is None
