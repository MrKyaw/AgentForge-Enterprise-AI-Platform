"""FinOps guardrails for model consumption."""

from __future__ import annotations

from typing import Protocol

from agentforge.errors import BudgetExceededError


class SpendSource(Protocol):
    def spend_today(self, tenant: str) -> float: ...


class BudgetGuard:
    """Hard daily budget per tenant, checked before each model invocation."""

    def __init__(self, usage: SpendSource, daily_budget_usd: float) -> None:
        self.usage = usage
        self.daily_budget_usd = float(daily_budget_usd)

    def check(self, tenant: str, projected_cost_usd: float = 0.0) -> float:
        """Return remaining budget or raise ``BudgetExceededError``."""
        spent = self.usage.spend_today(tenant)
        remaining = self.daily_budget_usd - spent
        if projected_cost_usd > max(remaining, 0.0):
            raise BudgetExceededError(
                "Daily AI consumption budget exceeded for this tenant.",
                details={
                    "tenant": tenant,
                    "budget_usd": round(self.daily_budget_usd, 4),
                    "spent_usd": round(spent, 6),
                    "projected_cost_usd": round(projected_cost_usd, 6),
                    "remaining_usd": round(max(remaining, 0.0), 6),
                },
            )
        return max(remaining, 0.0)
