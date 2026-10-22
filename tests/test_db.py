"""The SQLite wrapper must be idempotent, transactional, and thread-safe enough."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from agentforge.db import Database


def test_schema_is_created_idempotently(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "agentforge.db"
    first = Database(path)
    try:
        assert first.ping() is True
        tables = {
            row["name"]
            for row in first.query("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert {
            "documents",
            "chunks",
            "embeddings",
            "audit_events",
            "usage_ledger",
            "runs",
            "approvals",
        } <= tables
    finally:
        first.close()

    second = Database(path)
    try:
        assert second.ping() is True
    finally:
        second.close()


def test_execute_query_and_scalar() -> None:
    db = Database(":memory:")
    try:
        cursor = db.execute(
            "INSERT INTO usage_ledger "
            "(id, ts, tenant, agent, model, prompt_tokens, completion_tokens, cost_usd) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("use_1", "2026-01-01T00:00:00Z", "demo", "agent", "model", 10, 5, 0.1),
        )
        assert cursor.rowcount == 1
        row = db.query_one("SELECT * FROM usage_ledger WHERE id = ?", ("use_1",))
        assert row is not None
        assert row["tenant"] == "demo"
        assert db.scalar("SELECT cost_usd FROM usage_ledger WHERE id = ?", ("use_1",)) == 0.1
        assert (
            db.scalar("SELECT cost_usd FROM usage_ledger WHERE id = 'missing'", default="fallback")
            == "fallback"
        )
        assert db.query("SELECT 1")[0][0] == 1
    finally:
        db.close()


def test_executemany_inserts_all_rows() -> None:
    db = Database(":memory:")
    try:
        db.executemany(
            "INSERT INTO usage_ledger "
            "(id, ts, tenant, agent, model, prompt_tokens, completion_tokens, cost_usd) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (f"use_{index}", "2026-01-01T00:00:00Z", "demo", "a", "m", 1, 1, 0.01)
                for index in range(3)
            ],
        )
        assert db.scalar("SELECT COUNT(*) FROM usage_ledger") == 3
    finally:
        db.close()


def test_transaction_commits_and_rolls_back() -> None:
    db = Database(":memory:")
    try:
        with db.transaction() as connection:
            connection.execute(
                "INSERT INTO usage_ledger "
                "(id, ts, tenant, agent, model, prompt_tokens, completion_tokens, cost_usd) "
                "VALUES ('a', 't', 'demo', 'a', 'm', 1, 1, 0.0)"
            )
        assert db.scalar("SELECT COUNT(*) FROM usage_ledger") == 1

        with pytest.raises(RuntimeError), db.transaction() as connection:
            connection.execute(
                "INSERT INTO usage_ledger "
                "(id, ts, tenant, agent, model, prompt_tokens, completion_tokens, cost_usd) "
                "VALUES ('b', 't', 'demo', 'a', 'm', 1, 1, 0.0)"
            )
            raise RuntimeError("boom")
        assert db.scalar("SELECT COUNT(*) FROM usage_ledger") == 1
    finally:
        db.close()


def test_foreign_keys_cascade_and_constraints_enforced() -> None:
    db = Database(":memory:")
    try:
        db.execute(
            "INSERT INTO documents "
            "(id, collection, title, content_hash, created_at) VALUES (?, ?, ?, ?, ?)",
            ("doc_1", "research", "Title", "hash", "2026-01-01T00:00:00Z"),
        )
        db.execute(
            "INSERT INTO chunks (id, document_id, collection, ordinal, content, token_estimate) "
            "VALUES ('chk_1', 'doc_1', 'research', 0, 'text', 2)"
        )
        assert db.scalar("SELECT COUNT(*) FROM chunks") == 1

        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                "INSERT INTO documents "
                "(id, collection, title, content_hash, created_at) VALUES (?, ?, ?, ?, ?)",
                ("doc_1", "research", "Title", "hash", "2026-01-01T00:00:00Z"),
            )
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                "INSERT INTO chunks "
                "(id, document_id, collection, ordinal, content, token_estimate) "
                "VALUES ('chk_orphan', 'doc_missing', 'research', 0, 'text', 2)"
            )

        db.execute("DELETE FROM documents WHERE id = 'doc_1'")
        assert db.scalar("SELECT COUNT(*) FROM chunks") == 0
    finally:
        db.close()


def test_context_manager_closes_database() -> None:
    with Database(":memory:") as db:
        assert db.ping() is True
