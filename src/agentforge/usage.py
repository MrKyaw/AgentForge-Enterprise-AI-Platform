"""AI consumption ledger and cost transparency."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from agentforge.db import Database
from agentforge.models import TokenUsage
from agentforge.util import new_id, now_iso, today_utc


class UsageStore:
    def __init__(self, db: Database) -> None:
        self.db = db

    def record(
        self,
        *,
        tenant: str,
        agent: str,
        model: str,
        usage: TokenUsage,
        cost_usd: float,
        cached: bool,
        latency_ms: float,
        run_id: str = "",
    ) -> str:
        entry_id = new_id("use")
        self.db.execute(
            """
            INSERT INTO usage_ledger
                (id, ts, tenant, agent, model, prompt_tokens, completion_tokens,
                 cost_usd, cached, latency_ms, run_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entry_id,
                now_iso(),
                tenant,
                agent,
                model,
                usage.prompt_tokens,
                usage.completion_tokens,
                round(cost_usd, 8),
                1 if cached else 0,
                latency_ms,
                run_id,
            ),
        )
        return entry_id

    def spend_today(self, tenant: str) -> float:
        value = self.db.scalar(
            "SELECT COALESCE(SUM(cost_usd), 0) FROM usage_ledger "
            "WHERE tenant = ? AND substr(ts, 1, 10) = ?",
            (tenant, today_utc()),
            default=0.0,
        )
        return float(value or 0.0)

    def summary(self, tenant: str, days: int = 7) -> dict[str, Any]:
        days = max(1, min(days, 90))
        cutoff = (datetime.now(UTC).date() - timedelta(days=days - 1)).isoformat()
        rows = self.db.query(
            """
            SELECT substr(ts, 1, 10) AS day, model, agent,
                   COUNT(*) AS requests,
                   SUM(prompt_tokens) AS prompt_tokens,
                   SUM(completion_tokens) AS completion_tokens,
                   SUM(cost_usd) AS cost_usd,
                   SUM(cached) AS cached_requests
            FROM usage_ledger
            WHERE tenant = ? AND substr(ts, 1, 10) >= ?
            GROUP BY day, model, agent
            ORDER BY day ASC
            """,
            (tenant, cutoff),
        )
        by_model: dict[str, dict[str, float]] = {}
        daily: dict[str, dict[str, float]] = {}
        total_cost = 0.0
        total_tokens = 0
        requests = 0
        cached = 0
        for row in rows:
            cost = float(row["cost_usd"] or 0.0)
            tokens = int(row["prompt_tokens"] or 0) + int(row["completion_tokens"] or 0)
            total_cost += cost
            total_tokens += tokens
            requests += int(row["requests"])
            cached += int(row["cached_requests"] or 0)
            model_bucket = by_model.setdefault(
                row["model"], {"requests": 0, "tokens": 0, "cost_usd": 0.0}
            )
            model_bucket["requests"] += int(row["requests"])
            model_bucket["tokens"] += tokens
            model_bucket["cost_usd"] += cost
            day_bucket = daily.setdefault(row["day"], {"requests": 0, "tokens": 0, "cost_usd": 0.0})
            day_bucket["requests"] += int(row["requests"])
            day_bucket["tokens"] += tokens
            day_bucket["cost_usd"] += cost
        return {
            "tenant": tenant,
            "days": days,
            "requests": requests,
            "cached_requests": cached,
            "total_tokens": total_tokens,
            "total_cost_usd": round(total_cost, 6),
            "spend_today_usd": round(self.spend_today(tenant), 6),
            "by_model": [
                {
                    "model": model,
                    **{
                        key: round(value, 6) if key == "cost_usd" else value
                        for key, value in bucket.items()
                    },
                }
                for model, bucket in sorted(by_model.items())
            ],
            "daily": [
                {
                    "date": day,
                    **{
                        key: round(value, 6) if key == "cost_usd" else value
                        for key, value in bucket.items()
                    },
                }
                for day, bucket in sorted(daily.items())
            ],
        }

    def recent(self, tenant: str, limit: int = 20) -> list[dict[str, Any]]:
        rows = self.db.query(
            "SELECT * FROM usage_ledger WHERE tenant = ? ORDER BY ts DESC LIMIT ?",
            (tenant, max(1, min(limit, 200))),
        )
        return [dict(row) for row in rows]
