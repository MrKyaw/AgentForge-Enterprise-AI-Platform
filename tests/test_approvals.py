"""Human approval workflow, including role and tenant enforcement."""

from __future__ import annotations

import pytest

from agentforge.approvals import ApprovalService
from agentforge.audit import AuditLog
from agentforge.db import Database
from agentforge.errors import ConflictError, NotFoundError
from agentforge.models import ApprovalStatus, Principal


@pytest.fixture()
def service():
    db = Database(":memory:")
    audit = AuditLog(db)
    yield ApprovalService(db, audit), audit
    db.close()


def _request(service: ApprovalService, tenant: str = "demo"):
    return service.request(
        tenant=tenant,
        run_id="run_1",
        agent="portfolio-ops-copilot",
        tool="create_rebalance_task",
        arguments={"portfolio_id": "NW-1042", "reason": "drift"},
        requested_by="key_analyst",
    )


def test_request_persists_and_audits(service) -> None:
    approvals, audit = service
    approval = _request(approvals)
    assert approval.status is ApprovalStatus.PENDING
    assert approval.id.startswith("apr_")
    assert approvals.pending_count("demo") == 1
    assert approvals.pending_count("other") == 0
    events = audit.list_events(event_type="approval.requested")
    assert len(events) == 1
    assert events[0]["payload"]["tool"] == "create_rebalance_task"


def test_get_enforces_tenant_isolation(service) -> None:
    approvals, _ = service
    approval = _request(approvals)
    assert approvals.get(approval.id).id == approval.id
    assert approvals.get(approval.id, tenant="demo").id == approval.id
    with pytest.raises(NotFoundError):
        approvals.get(approval.id, tenant="other")
    with pytest.raises(NotFoundError):
        approvals.get("apr_missing")


def test_list_and_filter_by_status(service) -> None:
    approvals, _ = service
    first = _request(approvals)
    second = _request(approvals, tenant="research")
    admin = Principal(tenant="demo", role="admin", key_id="key_admin")

    approvals.decide(first.id, admin, approve=True)
    assert len(approvals.list("demo")) == 1
    assert len(approvals.list("demo", status=ApprovalStatus.APPROVED)) == 1
    assert approvals.list("demo", status=ApprovalStatus.PENDING) == []
    assert len(approvals.list("research")) == 1
    assert second.tenant == "research"


def test_admin_can_approve_or_reject(service) -> None:
    approvals, audit = service
    admin = Principal(tenant="demo", role="admin", key_id="key_admin")

    approved = approvals.decide(_request(approvals).id, admin, approve=True)
    assert approved.status is ApprovalStatus.APPROVED
    assert approved.decided_by == "key_admin"
    assert approved.decided_at is not None

    rejected = approvals.decide(_request(approvals).id, admin, approve=False)
    assert rejected.status is ApprovalStatus.REJECTED

    event_types = {event["event_type"] for event in audit.list_events()}
    assert {"approval.approved", "approval.rejected"} <= event_types


def test_only_admins_can_decide(service) -> None:
    approvals, _ = service
    approval = _request(approvals)
    analyst = Principal(tenant="demo", role="analyst", key_id="key_analyst")
    with pytest.raises(Exception, match="not permitted"):
        approvals.decide(approval.id, analyst, approve=True)
    assert approvals.get(approval.id).status is ApprovalStatus.PENDING


def test_cannot_decide_twice(service) -> None:
    approvals, _ = service
    admin = Principal(tenant="demo", role="admin", key_id="key_admin")
    approval = _request(approvals)
    approvals.decide(approval.id, admin, approve=True)
    with pytest.raises(ConflictError):
        approvals.decide(approval.id, admin, approve=False)


def test_attach_result_marks_success_or_failure(service) -> None:
    approvals, _ = service
    success = _request(approvals)
    attached = approvals.attach_result(success.id, {"task_id": "rbl_1"})
    assert attached.status is ApprovalStatus.APPROVED
    assert attached.result == {"task_id": "rbl_1"}

    failure = _request(approvals)
    attached = approvals.attach_result(failure.id, {"error": "bad"}, failed=True)
    assert attached.status is ApprovalStatus.FAILED
    assert attached.result == {"error": "bad"}
