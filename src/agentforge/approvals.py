"""Human-in-the-loop approval workflow for sensitive tools."""

from __future__ import annotations

import json
from typing import Any

from agentforge.audit import AuditLog
from agentforge.auth import Authenticator
from agentforge.db import Database
from agentforge.errors import ConflictError, NotFoundError
from agentforge.models import Approval, ApprovalStatus, Principal
from agentforge.util import new_id, now_iso, safe_json_loads


class ApprovalService:
    def __init__(self, db: Database, audit: AuditLog) -> None:
        self.db = db
        self.audit = audit

    def request(
        self,
        *,
        tenant: str,
        run_id: str,
        agent: str,
        tool: str,
        arguments: dict[str, Any],
        requested_by: str,
    ) -> Approval:
        approval = Approval(
            id=new_id("apr"),
            tenant=tenant,
            run_id=run_id,
            agent=agent,
            tool=tool,
            arguments=arguments,
            requested_by=requested_by,
            requested_at=now_iso(),
        )
        self.db.execute(
            """
            INSERT INTO approvals
                (id, ts, tenant, run_id, agent, tool, arguments, status, requested_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                approval.id,
                approval.requested_at,
                approval.tenant,
                approval.run_id,
                approval.agent,
                approval.tool,
                json.dumps(arguments, sort_keys=True),
                approval.status.value,
                approval.requested_by,
            ),
        )
        self.audit.record(
            "approval.requested",
            tenant=tenant,
            actor=requested_by,
            resource=approval.id,
            payload={"run_id": run_id, "agent": agent, "tool": tool},
        )
        return approval

    def get(self, approval_id: str, tenant: str | None = None) -> Approval:
        row = self.db.query_one("SELECT * FROM approvals WHERE id = ?", (approval_id,))
        if row is None:
            raise NotFoundError(f"Approval not found: {approval_id}")
        approval = _row_to_approval(row)
        if tenant is not None and approval.tenant != tenant:
            raise NotFoundError(f"Approval not found: {approval_id}")
        return approval

    def list(self, tenant: str, status: ApprovalStatus | None = None) -> list[Approval]:
        if status:
            rows = self.db.query(
                "SELECT * FROM approvals WHERE tenant = ? AND status = ? ORDER BY ts DESC",
                (tenant, status.value),
            )
        else:
            rows = self.db.query(
                "SELECT * FROM approvals WHERE tenant = ? ORDER BY ts DESC", (tenant,)
            )
        return [_row_to_approval(row) for row in rows]

    def pending_count(self, tenant: str) -> int:
        return int(
            self.db.scalar(
                "SELECT COUNT(*) FROM approvals WHERE tenant = ? AND status = 'pending'",
                (tenant,),
                0,
            )
        )

    def decide(self, approval_id: str, principal: Principal, *, approve: bool) -> Approval:
        approval = self.get(approval_id, tenant=principal.tenant)
        Authenticator.require_admin(principal)
        if approval.status != ApprovalStatus.PENDING:
            raise ConflictError(
                f"Approval '{approval_id}' is already {approval.status.value}.",
            )
        status = ApprovalStatus.APPROVED if approve else ApprovalStatus.REJECTED
        decided_at = now_iso()
        self.db.execute(
            "UPDATE approvals SET status = ?, decided_by = ?, decided_at = ? WHERE id = ?",
            (status.value, principal.key_id, decided_at, approval_id),
        )
        event = "approval.approved" if approve else "approval.rejected"
        self.audit.record(
            event,
            tenant=approval.tenant,
            actor=principal.key_id,
            resource=approval.id,
            payload={
                "run_id": approval.run_id,
                "tool": approval.tool,
                "agent": approval.agent,
            },
        )
        return self.get(approval_id)

    def attach_result(
        self,
        approval_id: str,
        result: dict[str, Any],
        *,
        failed: bool = False,
    ) -> Approval:
        status = ApprovalStatus.FAILED if failed else ApprovalStatus.APPROVED
        self.db.execute(
            "UPDATE approvals SET status = ?, result = ? WHERE id = ?",
            (status.value, json.dumps(result, sort_keys=True, default=str), approval_id),
        )
        return self.get(approval_id)


def _row_to_approval(row: Any) -> Approval:
    return Approval(
        id=row["id"],
        tenant=row["tenant"],
        run_id=row["run_id"],
        agent=row["agent"],
        tool=row["tool"],
        arguments=safe_json_loads(row["arguments"], {}),
        status=ApprovalStatus(row["status"]),
        requested_by=row["requested_by"],
        requested_at=row["ts"],
        decided_by=row["decided_by"],
        decided_at=row["decided_at"],
        result=safe_json_loads(row["result"], None),
    )
