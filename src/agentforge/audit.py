"""Append-only, hash-chained audit trail.

Each event commits to the previous event's hash. Removing or editing history
breaks verification, which gives reviewers a cheap tamper-evidence check.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from typing import Any

from agentforge.db import Database
from agentforge.models import AuditVerification
from agentforge.util import canonical_json, new_id, now_iso, safe_json_loads, sha256_text


class AuditLog:
    def __init__(
        self,
        db: Database,
        clock: Callable[[], str] = now_iso,
    ) -> None:
        self.db = db
        self._clock = clock

    def record(
        self,
        event_type: str,
        *,
        tenant: str = "",
        actor: str = "",
        resource: str = "",
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Append an event and return its materialized representation."""
        body = payload or {}
        event = {
            "event_id": new_id("evt"),
            "ts": self._clock(),
            "event_type": event_type,
            "tenant": tenant,
            "actor": actor,
            "resource": resource,
            "payload": body,
        }
        with self.db.transaction() as connection:
            previous = connection.execute(
                "SELECT hash FROM audit_events ORDER BY seq DESC LIMIT 1"
            ).fetchone()
            prev_hash = previous["hash"] if previous else ""
            event["prev_hash"] = prev_hash
            event["hash"] = sha256_text(canonical_json(event))
            connection.execute(
                """
                INSERT INTO audit_events
                    (event_id, ts, event_type, tenant, actor, resource, payload, prev_hash, hash)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event["event_id"],
                    event["ts"],
                    event["event_type"],
                    event["tenant"],
                    event["actor"],
                    event["resource"],
                    canonical_json(body),
                    prev_hash,
                    event["hash"],
                ),
            )
        return event

    def list_events(
        self,
        *,
        tenant: str | None = None,
        event_type: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if tenant is not None:
            clauses.append("tenant = ?")
            params.append(tenant)
        if event_type is not None:
            clauses.append("event_type = ?")
            params.append(event_type)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self.db.query(
            f"SELECT * FROM audit_events {where} ORDER BY seq DESC LIMIT ?",
            (*params, max(1, min(limit, 1000))),
        )
        return [
            {
                "seq": row["seq"],
                "event_id": row["event_id"],
                "ts": row["ts"],
                "event_type": row["event_type"],
                "tenant": row["tenant"],
                "actor": row["actor"],
                "resource": row["resource"],
                "payload": safe_json_loads(row["payload"], {}),
                "prev_hash": row["prev_hash"],
                "hash": row["hash"],
            }
            for row in rows
        ]

    def verify(self) -> AuditVerification:
        """Recompute the full chain and report the first broken link."""
        rows = self.db.query("SELECT * FROM audit_events ORDER BY seq ASC")
        previous_hash = ""
        for row in rows:
            body = {
                "event_id": row["event_id"],
                "ts": row["ts"],
                "event_type": row["event_type"],
                "tenant": row["tenant"],
                "actor": row["actor"],
                "resource": row["resource"],
                "payload": safe_json_loads(row["payload"], {}),
                "prev_hash": row["prev_hash"],
                "hash": row["hash"],
            }
            expected = sha256_text(
                canonical_json({key: value for key, value in body.items() if key != "hash"})
            )
            if row["prev_hash"] != previous_hash or row["hash"] != expected:
                return AuditVerification(
                    ok=False,
                    events=len(rows),
                    broken_at=row["seq"],
                    message="Audit chain verification failed; history may have been altered.",
                )
            previous_hash = row["hash"]
        return AuditVerification(
            ok=True,
            events=len(rows),
            message="Audit chain verified.",
        )

    def export_jsonl(self, path: str) -> int:
        """Write the complete chain to a JSONL file for evidence retention."""
        events = list(reversed(self.list_events(limit=1000)))
        with open(path, "w", encoding="utf-8") as handle:
            for event in events:
                handle.write(canonical_json(event) + "\n")
        return len(events)

    @staticmethod
    def tamper_for_testing(db: Database, seq: int, payload: str) -> None:
        """Test helper that simulates an out-of-band database edit."""
        with db.transaction() as connection:
            connection.execute("UPDATE audit_events SET payload = ? WHERE seq = ?", (payload, seq))


def _row_hash(connection: sqlite3.Connection) -> str:  # pragma: no cover - diagnostic helper
    row = connection.execute("SELECT hash FROM audit_events ORDER BY seq DESC LIMIT 1").fetchone()
    return row["hash"] if row else ""
