"""Guardrails: PII redaction, prompt-injection scoring, and data classification."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from agentforge.models import Classification

CLASSIFICATION_ORDER: dict[Classification, int] = {
    Classification.PUBLIC: 0,
    Classification.INTERNAL: 1,
    Classification.CONFIDENTIAL: 2,
    Classification.RESTRICTED: 3,
}

ROLE_CLASSIFICATIONS: dict[str, set[Classification]] = {
    "viewer": {Classification.PUBLIC},
    "analyst": {
        Classification.PUBLIC,
        Classification.INTERNAL,
        Classification.CONFIDENTIAL,
    },
    "admin": set(Classification),
}


def classification_at_most(level: Classification) -> set[Classification]:
    """Return every classification up to and including ``level``."""
    ceiling = CLASSIFICATION_ORDER[level]
    return {item for item, rank in CLASSIFICATION_ORDER.items() if rank <= ceiling}


def allowed_classifications(
    role: str, ceiling: Classification | None = None
) -> set[Classification]:
    """Intersect a role's clearance with an optional agent ceiling."""
    role_set = ROLE_CLASSIFICATIONS.get(role, set())
    if ceiling is None:
        return role_set
    return role_set & classification_at_most(ceiling)


_PII_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "email",
        re.compile(r"\b[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}\b", re.IGNORECASE),
    ),
    (
        "phone",
        re.compile(r"(?<!\w)(?:\+?1[\s.-]?)?(?:\(\d{3}\)|\d{3})[\s.-]\d{3}[\s.-]\d{4}(?!\w)"),
    ),
    (
        "sin",
        re.compile(r"\b\d{3}[\s-]\d{3}[\s-]\d{3}\b"),
    ),
    (
        "credit_card",
        re.compile(r"\b(?:\d[ -]*?){13,19}\b"),
    ),
    (
        "secret",
        re.compile(r"\b(?:sk|pk|api|key|token)[-_][A-Za-z0-9]{16,}\b", re.IGNORECASE),
    ),
    (
        "iban",
        re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b"),
    ),
)

_INJECTION_SIGNALS: tuple[tuple[re.Pattern[str], float, str], ...] = (
    (
        re.compile(
            r"\b(ignore|disregard|forget)\b.{0,24}\b(previous|prior|all|above)\b.{0,16}\b"
            r"(instructions?|prompts?|rules?)\b",
            re.IGNORECASE | re.DOTALL,
        ),
        0.65,
        "instruction_override",
    ),
    (
        re.compile(
            r"\b(reveal|show|print|repeat|leak)\b.{0,24}\b(system|developer|hidden)\b.{0,16}"
            r"\b(prompt|message|instructions?)\b",
            re.IGNORECASE | re.DOTALL,
        ),
        0.6,
        "prompt_exfiltration",
    ),
    (
        re.compile(r"\b(jailbreak|developer mode|do anything now|DAN mode)\b", re.IGNORECASE),
        0.55,
        "jailbreak_phrase",
    ),
    (
        re.compile(
            r"\b(bypass|disable|circumvent)\b.{0,24}\b(guardrails?|safety|policy|filters?)\b",
            re.IGNORECASE | re.DOTALL,
        ),
        0.55,
        "guardrail_bypass",
    ),
    (
        re.compile(
            r"\b(exfiltrate|send|upload)\b.{0,32}\b(api key|credentials?|secrets?|customer data)\b",
            re.IGNORECASE | re.DOTALL,
        ),
        0.6,
        "data_exfiltration",
    ),
    (
        re.compile(r"\bnew instructions?\s*:", re.IGNORECASE),
        0.35,
        "injected_instructions",
    ),
    (
        re.compile(r"\bact as\b.{0,20}\b(unrestricted|uncensored|root|system)\b", re.IGNORECASE),
        0.4,
        "role_override",
    ),
)


@dataclass(slots=True)
class RedactionResult:
    text: str
    counts: dict[str, int] = field(default_factory=dict)

    @property
    def total(self) -> int:
        return sum(self.counts.values())


@dataclass(slots=True)
class InjectionAssessment:
    score: float
    signals: list[str] = field(default_factory=list)

    @property
    def suspicious(self) -> bool:
        return self.score > 0


def _luhn_valid(candidate: str) -> bool:
    digits = [int(char) for char in candidate if char.isdigit()]
    if len(digits) < 13 or len(digits) > 19:
        return False
    checksum = 0
    parity = len(digits) % 2
    for index, digit in enumerate(digits):
        if index % 2 == parity:
            digit *= 2
            if digit > 9:
                digit -= 9
        checksum += digit
    return checksum % 10 == 0


def redact_pii(text: str) -> RedactionResult:
    """Redact common personal and secret identifiers.

    Credit-card candidates are only redacted when they pass a Luhn check, which
    avoids mangling ordinary numeric ranges such as AUM figures.
    """
    counts: dict[str, int] = {}
    redacted = text
    for label, pattern in _PII_PATTERNS:
        if label == "credit_card":

            def replace_card(match: re.Match[str], _label: str = label) -> str:
                value = match.group(0)
                if _luhn_valid(value):
                    counts[_label] = counts.get(_label, 0) + 1
                    return f"[REDACTED:{_label.upper()}]"
                return value

            redacted = pattern.sub(replace_card, redacted)
        else:

            def replace(match: re.Match[str], _label: str = label) -> str:
                counts[_label] = counts.get(_label, 0) + 1
                return f"[REDACTED:{_label.upper()}]"

            redacted = pattern.sub(replace, redacted)
    return RedactionResult(text=redacted, counts=counts)


def assess_injection(text: str) -> InjectionAssessment:
    """Heuristic prompt-injection score in the range 0..1.

    This is a fast pre-filter, not a complete defence. The score is deliberately
    transparent so it can be logged, tuned, and supplemented by a model-based
    classifier in regulated deployments.
    """
    score = 0.0
    signals: list[str] = []
    for pattern, weight, name in _INJECTION_SIGNALS:
        if pattern.search(text):
            score += weight
            signals.append(name)
    if "```" in text and text.lower().count("instruction") >= 2:
        score += 0.2
        signals.append("instruction_in_code_block")
    return InjectionAssessment(score=round(min(score, 1.0), 3), signals=signals)


def is_refusal(answer: str) -> bool:
    """Detect a grounded refusal so evaluation can distinguish it from failure."""
    lowered = answer.lower()
    phrases = (
        "don't have enough",
        "do not have enough",
        "not enough grounded",
        "insufficient evidence",
        "unable to find",
        "cannot find",
        "no relevant",
        "not available in the approved",
    )
    return any(phrase in lowered for phrase in phrases)
