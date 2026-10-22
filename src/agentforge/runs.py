"""Persistence for run results and traces."""

from __future__ import annotations

from agentforge.db import Database
from agentforge.errors import NotFoundError
from agentforge.models import RunResult


class RunStore:
    def __init__(self, db: Database) -> None:
        self.db = db

    def save(self, result: RunResult, tenant: str) -> None:
        self.db.execute(
            """
            INSERT INTO runs (run_id, ts, tenant, agent, status, trace_id, result)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(run_id) DO UPDATE SET
                status = excluded.status,
                result = excluded.result
            """,
            (
                result.run_id,
                result.created_at,
                tenant,
                result.agent,
                result.status.value,
                result.trace_id,
                result.model_dump_json(),
            ),
        )

    def get(self, run_id: str, tenant: str | None = None) -> RunResult:
        row = self.db.query_one("SELECT * FROM runs WHERE run_id = ?", (run_id,))
        if row is None:
            raise NotFoundError(f"Run not found: {run_id}")
        if tenant is not None and row["tenant"] != tenant:
            raise NotFoundError(f"Run not found: {run_id}")
        return RunResult.model_validate_json(row["result"])

    def list(self, tenant: str, limit: int = 20) -> list[RunResult]:
        rows = self.db.query(
            "SELECT result FROM runs WHERE tenant = ? ORDER BY ts DESC LIMIT ?",
            (tenant, max(1, min(limit, 100))),
        )
        return [RunResult.model_validate_json(row["result"]) for row in rows]

    def count(self) -> int:
        return int(self.db.scalar("SELECT COUNT(*) FROM runs", default=0))
