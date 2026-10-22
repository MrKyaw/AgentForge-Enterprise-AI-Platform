"""Slow, full-workflow demonstration of the governed platform."""

from __future__ import annotations

import asyncio

import pytest

from agentforge.bootstrap import Container
from agentforge.models import RunRequest, RunStatus

run_async = asyncio.run


def _request(question: str) -> RunRequest:
    return RunRequest(input=question)


@pytest.mark.slow
def test_complete_governed_workflow(seeded: Container) -> None:
    admin = seeded.principal("admin")

    research = run_async(
        seeded.runtime.run(
            "research-copilot",
            _request(
                "What is the maximum position size for a single issuer in the core equity strategy?"
            ),
            admin,
        )
    )
    assert research.status is RunStatus.COMPLETED
    assert "5%" in research.answer
    assert research.citations

    rebalance = run_async(
        seeded.runtime.run(
            "portfolio-ops-copilot",
            _request(
                "Rebalance portfolio NW-1042 because the target weights have drifted beyond policy."
            ),
            admin,
        )
    )
    assert rebalance.status is RunStatus.PENDING_APPROVAL
    assert rebalance.approval_id

    approval, executed = run_async(
        seeded.runtime.execute_approval(rebalance.approval_id, admin, approve=True)
    )
    assert approval.result["status"] == "created"
    assert executed.status is RunStatus.COMPLETED
    assert executed.tools_used[-1].requires_approval is True

    verification = seeded.audit.verify()
    assert verification.ok is True
    assert verification.events >= 6

    usage = seeded.usage.summary("demo")
    assert usage["requests"] >= 2
    assert usage["total_cost_usd"] == 0.0  # offline local provider

    assert seeded.runs.count() == 2
    assert seeded.approvals.pending_count("demo") == 0
    assert seeded.metrics.render().strip()
