"""Approvals, audit evidence, and evaluation endpoints."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Query

from agentforge.api.deps import get_admin, get_container, get_principal
from agentforge.api.schemas import ApprovalDecisionResponse, EvalRequest
from agentforge.bootstrap import Container
from agentforge.evals.harness import load_cases
from agentforge.models import (
    Approval,
    ApprovalStatus,
    AuditVerification,
    EvalReport,
    Principal,
)

router = APIRouter(prefix="/v1", tags=["Governance"])


@router.get(
    "/approvals",
    response_model=list[Approval],
    summary="List approval requests for the tenant",
)
def list_approvals(
    status: ApprovalStatus | None = Query(default=None),
    principal: Principal = Depends(get_principal),
    container: Container = Depends(get_container),
) -> list[Approval]:
    return container.approvals.list(principal.tenant, status=status)


@router.post(
    "/approvals/{approval_id}/approve",
    response_model=ApprovalDecisionResponse,
    summary="Approve and execute a gated action (admin)",
)
async def approve(
    approval_id: str,
    principal: Principal = Depends(get_admin),
    container: Container = Depends(get_container),
) -> ApprovalDecisionResponse:
    approval, run = await container.runtime.execute_approval(approval_id, principal, approve=True)
    return ApprovalDecisionResponse(approval=approval, run=run)


@router.post(
    "/approvals/{approval_id}/reject",
    response_model=ApprovalDecisionResponse,
    summary="Reject a gated action (admin)",
)
async def reject(
    approval_id: str,
    principal: Principal = Depends(get_admin),
    container: Container = Depends(get_container),
) -> ApprovalDecisionResponse:
    approval, run = await container.runtime.execute_approval(approval_id, principal, approve=False)
    return ApprovalDecisionResponse(approval=approval, run=run)


@router.get(
    "/audit",
    summary="Read tamper-evident audit events (admin)",
)
def audit_events(
    limit: int = Query(default=100, ge=1, le=1000),
    event_type: str | None = Query(default=None),
    principal: Principal = Depends(get_admin),
    container: Container = Depends(get_container),
) -> list[dict]:
    return container.audit.list_events(
        tenant=principal.tenant,
        event_type=event_type,
        limit=limit,
    )


@router.get(
    "/audit/verify",
    response_model=AuditVerification,
    summary="Recompute the audit hash chain (admin)",
)
def verify_audit(
    _principal: Principal = Depends(get_admin),
    container: Container = Depends(get_container),
) -> AuditVerification:
    return container.audit.verify()


@router.post(
    "/evals/run",
    response_model=EvalReport,
    summary="Run the golden evaluation set (admin)",
)
async def run_evals(
    body: EvalRequest,
    principal: Principal = Depends(get_admin),
    container: Container = Depends(get_container),
) -> EvalReport:
    path = Path(container.settings.resolved_data_dir()) / "evals" / "golden_set.jsonl"
    cases = load_cases(path)
    return await container.evals.run(cases, principal, tags=set(body.tags) or None)
