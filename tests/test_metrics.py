"""Prometheus rendering and metric arithmetic."""

from __future__ import annotations

import pytest

from agentforge.metrics import BUCKETS, Metrics


def test_counters_gauges_and_labels() -> None:
    metrics = Metrics()
    metrics.inc("requests_total")
    metrics.inc("requests_total", 2)
    metrics.inc("requests_total", status="200", method="GET")
    metrics.set_gauge("queue_depth", 4, queue="approvals")

    assert metrics.counter_value("requests_total") == 3
    assert metrics.counter_value("requests_total", status="200", method="GET") == 1
    rendered = metrics.render()
    assert "requests_total 3" in rendered
    assert 'requests_total{method="GET",status="200"} 1' in rendered
    assert 'queue_depth{queue="approvals"} 4' in rendered


def test_histogram_buckets_and_render() -> None:
    metrics = Metrics()
    metrics.observe("latency_seconds", 0.003)
    metrics.observe("latency_seconds", 0.2)
    assert metrics.histogram_count("latency_seconds") == 2

    rendered = metrics.render()
    assert 'latency_seconds_bucket{le="0.005"} 1' in rendered
    assert 'latency_seconds_bucket{le="0.25"} 2' in rendered
    assert 'latency_seconds_bucket{le="+Inf"} 2' in rendered
    assert "latency_seconds_count 2" in rendered
    assert "latency_seconds_sum " in rendered
    for boundary in BUCKETS:
        assert f'le="{boundary}"' in rendered


def test_time_context_manager_observes_duration() -> None:
    metrics = Metrics()
    with metrics.time("operation_seconds", op="demo"):
        pass
    assert metrics.histogram_count("operation_seconds", op="demo") == 1
    rendered = metrics.render()
    assert 'operation_seconds_count{op="demo"} 1' in rendered


def test_time_records_even_when_body_raises() -> None:
    metrics = Metrics()
    with pytest.raises(RuntimeError), metrics.time("operation_seconds"):
        raise RuntimeError("boom")
    assert metrics.histogram_count("operation_seconds") == 1


def test_label_values_are_escaped() -> None:
    metrics = Metrics()
    metrics.inc("custom_total", note='quote " and \\ slash\nnewline')
    rendered = metrics.render()
    assert 'note="quote \\" and \\\\ slash newline"' in rendered


def test_reset_clears_everything() -> None:
    metrics = Metrics()
    metrics.inc("a")
    metrics.set_gauge("b", 1)
    metrics.observe("c", 0.1)
    metrics.reset()
    assert metrics.render() == ""
    assert metrics.counter_value("a") == 0
    assert metrics.histogram_count("c") == 0
