"""Hash-chained audit evidence must detect tampering."""

from __future__ import annotations

import json
from pathlib import Path

from agentforge.audit import AuditLog
from agentforge.db import Database


def _log() -> tuple[Database, AuditLog]:
    db = Database(":memory:")
    return db, AuditLog(db)


def test_events_chain_and_verify() -> None:
    db, audit = _log()
    try:
        first = audit.record("run.started", tenant="demo", actor="key_1", resource="run_1")
        second = audit.record(
            "run.completed",
            tenant="demo",
            actor="key_1",
            resource="run_1",
            payload={"status": "completed"},
        )
        assert first["prev_hash"] == ""
        assert second["prev_hash"] == first["hash"]
        assert len(first["hash"]) == 64

        verification = audit.verify()
        assert verification.ok is True
        assert verification.events == 2
        assert verification.broken_at is None
        assert "verified" in verification.message.lower()
    finally:
        db.close()


def test_empty_chain_verifies() -> None:
    db, audit = _log()
    try:
        verification = audit.verify()
        assert verification.ok is True
        assert verification.events == 0
    finally:
        db.close()


def test_list_events_filters_and_orders() -> None:
    db, audit = _log()
    try:
        audit.record("run.started", tenant="demo")
        audit.record("knowledge.ingested", tenant="research")
        audit.record("run.completed", tenant="demo")

        assert [event["event_type"] for event in audit.list_events()] == [
            "run.completed",
            "knowledge.ingested",
            "run.started",
        ]
        assert len(audit.list_events(tenant="demo")) == 2
        assert len(audit.list_events(event_type="run.started")) == 1
        assert len(audit.list_events(limit=1)) == 1
        assert len(audit.list_events(limit=0)) == 1  # clamped to one
        assert audit.list_events(tenant="nobody") == []
    finally:
        db.close()


def test_tampering_breaks_verification() -> None:
    db, audit = _log()
    try:
        audit.record("run.started", tenant="demo", payload={"safe": True})
        audit.record("run.completed", tenant="demo", payload={"safe": True})
        AuditLog.tamper_for_testing(db, 1, json.dumps({"safe": False}, sort_keys=True))

        verification = audit.verify()
        assert verification.ok is False
        assert verification.broken_at == 1
        assert "altered" in verification.message
    finally:
        db.close()


def test_tampering_with_prev_hash_is_detected() -> None:
    db, audit = _log()
    try:
        audit.record("one")
        audit.record("two")
        with db.transaction() as connection:
            connection.execute("UPDATE audit_events SET prev_hash = 'forged' WHERE seq = 2")
        assert audit.verify().ok is False
    finally:
        db.close()


def test_export_jsonl_round_trips(tmp_path: Path) -> None:
    db, audit = _log()
    try:
        audit.record("run.started", tenant="demo", actor="key_1", resource="run_1")
        audit.record("run.completed", tenant="demo", payload={"ok": True})
        path = tmp_path / "audit.jsonl"
        assert audit.export_jsonl(str(path)) == 2

        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        assert [row["event_type"] for row in rows] == ["run.started", "run.completed"]
        assert rows[0]["seq"] == 1
        assert rows[1]["payload"] == {"ok": True}
    finally:
        db.close()
