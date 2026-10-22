"""Run persistence and tenant isolation."""

from __future__ import annotations

import pytest

from agentforge.db import Database
from agentforge.errors import NotFoundError
from agentforge.models import RunResult, RunStatus
from agentforge.runs import RunStore


def _result(run_id: str = "run_1", agent: str = "research-copilot") -> RunResult:
    return RunResult(
        run_id=run_id,
        agent=agent,
        agent_version="1.0.0",
        status=RunStatus.COMPLETED,
        answer="Answer [1].",
        trace_id="tr_1",
        model="local-grounded",
    )


def test_save_get_and_list() -> None:
    db = Database(":memory:")
    try:
        store = RunStore(db)
        store.save(_result(), tenant="demo")
        store.save(_result("run_2", "governance-advisor"), tenant="demo")
        store.save(_result("run_3"), tenant="research")

        assert store.count() == 3
        fetched = store.get("run_1", tenant="demo")
        assert fetched.answer == "Answer [1]."
        assert len(store.list("demo")) == 2
        assert len(store.list("research")) == 1
        assert len(store.list("demo", limit=1)) == 1
    finally:
        db.close()


def test_upsert_updates_status_and_result() -> None:
    db = Database(":memory:")
    try:
        store = RunStore(db)
        result = _result()
        store.save(result, tenant="demo")
        result.status = RunStatus.PENDING_APPROVAL
        result.answer = "Needs approval."
        store.save(result, tenant="demo")
        assert store.count() == 1
        assert store.get("run_1").status is RunStatus.PENDING_APPROVAL
        assert store.get("run_1").answer == "Needs approval."
    finally:
        db.close()


def test_tenant_isolation_and_missing_run() -> None:
    db = Database(":memory:")
    try:
        store = RunStore(db)
        store.save(_result(), tenant="demo")
        with pytest.raises(NotFoundError):
            store.get("run_1", tenant="research")
        with pytest.raises(NotFoundError):
            store.get("run_missing")
    finally:
        db.close()
