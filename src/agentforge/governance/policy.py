"""Pre-flight policy enforcement for agent runs."""

from __future__ import annotations

from dataclasses import dataclass, field

from agentforge.config import Settings
from agentforge.errors import PolicyViolation
from agentforge.models import AgentSpec, Classification, Lifecycle, Principal
from agentforge.security import (
    InjectionAssessment,
    allowed_classifications,
    assess_injection,
    redact_pii,
)


@dataclass(slots=True)
class PolicyDecision:
    redacted_input: str
    allowed_classifications: set[Classification]
    injection: InjectionAssessment
    redaction_counts: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    allowed_residencies: set[str] = field(default_factory=lambda: {"local", "canada", "global"})


class PolicyEngine:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def preflight(
        self,
        principal: Principal,
        agent: AgentSpec,
        user_input: str,
        requested_model: str | None = None,
    ) -> PolicyDecision:
        if agent.lifecycle != Lifecycle.ACTIVE:
            raise PolicyViolation(
                f"Agent '{agent.name}' is not active.",
                details={"lifecycle": agent.lifecycle.value},
            )
        if principal.tenant not in agent.entitlements:
            raise PolicyViolation(
                f"Tenant '{principal.tenant}' is not entitled to agent '{agent.name}'.",
                details={"entitlements": agent.entitlements},
            )
        if principal.role not in agent.allowed_roles:
            raise PolicyViolation(
                f"Role '{principal.role}' cannot run agent '{agent.name}'.",
                details={"allowed_roles": agent.allowed_roles},
            )
        if requested_model and requested_model not in agent.allowed_models:
            raise PolicyViolation(
                f"Model '{requested_model}' is not permitted for this agent.",
                details={"allowed_models": agent.allowed_models},
            )
        if len(user_input) > self.settings.max_input_chars:
            raise PolicyViolation(
                "Input exceeds the configured maximum length.",
                details={"max_input_chars": self.settings.max_input_chars},
            )

        injection = assess_injection(user_input)
        warnings: list[str] = []
        if injection.score >= self.settings.injection_threshold:
            raise PolicyViolation(
                "Potential prompt injection detected; request blocked.",
                details={"signals": injection.signals, "score": injection.score},
            )
        if injection.suspicious:
            warnings.append("prompt_injection_signals_detected")

        redaction = redact_pii(user_input)
        if redaction.total:
            warnings.append("input_pii_redacted")

        classifications = allowed_classifications(principal.role, agent.max_classification)
        residencies = {"local", "canada", "global"}
        if agent.max_classification == Classification.RESTRICTED:
            residencies = {"local", "canada"}
        if requested_model in {"local-grounded", "private"}:
            residencies = {"local"}

        return PolicyDecision(
            redacted_input=redaction.text,
            allowed_classifications=classifications,
            injection=injection,
            redaction_counts=redaction.counts,
            warnings=warnings,
            allowed_residencies=residencies,
        )

    @staticmethod
    def require_agent_access(principal: Principal, agent: AgentSpec) -> None:
        if principal.tenant not in agent.entitlements:
            raise PolicyViolation(
                f"Tenant '{principal.tenant}' is not entitled to agent '{agent.name}'."
            )
