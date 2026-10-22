"""Consumption ledger, aggregation, and hard budget guards."""

from __future__ import annotations

import pytest

from agentforge.cost import BudgetGuard
from agentforge.db import Database
from agentforge.errors import BudgetExceededError
from agentforge.models import TokenUsage
from agentforge.usage import UsageStore


def test_records_and_spend_today() -> None:
    db = Database(":memory:")
    try:
        usage = UsageStore(db)
        entry = usage.record(
            tenant="demo",
            agent="research-copilot",
            model="gpt-4.1-mini",
            usage=TokenUsage(prompt_tokens=100, completion_tokens=50),
            cost_usd=0.0012,
            cached=False,
            latency_ms=12.5,
            run_id="run_1",
        )
        assert entry.startswith("use_")
        assert usage.spend_today("demo") == pytest.approx(0.0012)
        assert usage.spend_today("other") == 0.0

        stored = usage.recent("demo")[0]
        assert stored["prompt_tokens"] == 100
        assert stored["completion_tokens"] == 50
        assert stored["cached"] == 0
        assert stored["run_id"] == "run_1"
    finally:
        db.close()


def test_summary_groups_by_model_and_day() -> None:
    db = Database(":memory:")
    try:
        usage = UsageStore(db)
        usage.record(
            tenant="demo",
            agent="a",
            model="m1",
            usage=TokenUsage(prompt_tokens=10, completion_tokens=5),
            cost_usd=0.01,
            cached=False,
            latency_ms=1,
        )
        usage.record(
            tenant="demo",
            agent="b",
            model="m2",
            usage=TokenUsage(prompt_tokens=20, completion_tokens=10),
            cost_usd=0.02,
            cached=True,
            latency_ms=2,
        )
        usage.record(
            tenant="other",
            agent="c",
            model="m3",
            usage=TokenUsage(prompt_tokens=99, completion_tokens=99),
            cost_usd=9.0,
            cached=False,
            latency_ms=3,
        )
        summary = usage.summary("demo", days=7)
        assert summary["requests"] == 2
        assert summary["cached_requests"] == 1
        assert summary["total_tokens"] == 45
        assert summary["total_cost_usd"] == pytest.approx(0.03)
        assert {item["model"] for item in summary["by_model"]} == {"m1", "m2"}
        assert len(summary["daily"]) == 1
        assert summary["daily"][0]["requests"] == 2
        assert summary["spend_today_usd"] == pytest.approx(0.03)

        clamped = usage.summary("demo", days=500)
        assert clamped["days"] == 90
        assert usage.recent("demo", limit=1) and len(usage.recent("demo", limit=1)) == 1
    finally:
        db.close()


def test_budget_guard_allows_and_rejects() -> None:
    db = Database(":memory:")
    try:
        usage = UsageStore(db)
        guard = BudgetGuard(usage, daily_budget_usd=1.0)
        assert guard.check("demo", 0.25) == 1.0

        usage.record(
            tenant="demo",
            agent="a",
            model="m",
            usage=TokenUsage(prompt_tokens=1, completion_tokens=1),
            cost_usd=0.9,
            cached=False,
            latency_ms=1,
        )
        assert guard.check("demo", 0.05) == pytest.approx(0.1)

        with pytest.raises(BudgetExceededError) as excinfo:
            guard.check("demo", 0.2)
        assert excinfo.value.status_code == 402
        assert excinfo.value.details["budget_usd"] == 1.0
        assert excinfo.value.details["spent_usd"] == pytest.approx(0.9)
        assert excinfo.value.details["remaining_usd"] == pytest.approx(0.1)
    finally:
        db.close()


def test_budget_guard_rejects_when_already_overspent() -> None:
    db = Database(":memory:")
    try:
        usage = UsageStore(db)
        usage.record(
            tenant="demo",
            agent="a",
            model="m",
            usage=TokenUsage(prompt_tokens=1, completion_tokens=1),
            cost_usd=2.0,
            cached=False,
            latency_ms=1,
        )
        with pytest.raises(BudgetExceededError):
            BudgetGuard(usage, 1.0).check("demo", 0.01)
        # A strictly free request is still allowed once the budget is exhausted.
        assert BudgetGuard(usage, 1.0).check("demo", 0.0) == 0.0
    finally:
        db.close()
