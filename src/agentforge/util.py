"""Small shared utilities with no project-internal dependencies."""

from __future__ import annotations

import hashlib
import json
import math
import re
import uuid
from datetime import UTC, datetime
from typing import Any

_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_\-']*%?", re.IGNORECASE)
_SPACE_RE = re.compile(r"\s+")

STOPWORDS: frozenset[str] = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "been",
        "being",
        "but",
        "by",
        "can",
        "could",
        "did",
        "do",
        "does",
        "for",
        "from",
        "had",
        "has",
        "have",
        "how",
        "i",
        "if",
        "in",
        "into",
        "is",
        "it",
        "its",
        "may",
        "might",
        "more",
        "most",
        "must",
        "my",
        "no",
        "not",
        "of",
        "on",
        "or",
        "our",
        "over",
        "should",
        "so",
        "than",
        "that",
        "the",
        "their",
        "them",
        "then",
        "there",
        "these",
        "they",
        "this",
        "those",
        "to",
        "under",
        "up",
        "us",
        "was",
        "we",
        "were",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "will",
        "with",
        "would",
        "you",
        "your",
    ]
)


def now_iso() -> str:
    """Return a timezone-aware UTC timestamp in ISO-8601 form."""
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def today_utc() -> str:
    """Return the current UTC date as YYYY-MM-DD."""
    return datetime.now(UTC).date().isoformat()


def new_id(prefix: str, length: int = 16) -> str:
    """Create a short, collision-resistant identifier such as ``run_ab12...``."""
    return f"{prefix}_{uuid.uuid4().hex[:length]}"


def sha256_text(value: str) -> str:
    """Stable SHA-256 hex digest."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def canonical_json(value: Any) -> str:
    """Canonical JSON used for hashing and deterministic audit records."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def safe_json_loads(value: str | None, default: Any = None) -> Any:
    """Parse JSON, returning ``default`` instead of raising."""
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def _stem(token: str) -> str:
    """Very small plural normalizer; deterministic and intentionally conservative."""
    if len(token) > 4 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def tokenize(text: str) -> list[str]:
    """Lowercase word tokenizer preserving percentages, hyphenated terms, and numbers."""
    return [_stem(match.group(0).lower()) for match in _TOKEN_RE.finditer(text)]


def content_tokens(text: str) -> list[str]:
    """Tokens with common English stopwords removed (used by the local composer)."""
    return [token for token in tokenize(text) if token not in STOPWORDS]


def normalize_whitespace(text: str) -> str:
    """Collapse runs of whitespace while preserving newlines as single spaces."""
    return _SPACE_RE.sub(" ", text).strip()


def clip(text: str, limit: int, suffix: str = "…") -> str:
    """Truncate text at a word boundary where possible."""
    if len(text) <= limit:
        return text
    if limit <= len(suffix):
        return text[:limit]
    cut = text[: limit - len(suffix)]
    boundary = cut.rfind(" ")
    if boundary > limit * 0.6:
        cut = cut[:boundary]
    return cut.rstrip() + suffix


def estimate_tokens(text: str) -> int:
    """Cheap, deterministic token estimate (~4 characters per token, minimum 1)."""
    return max(1, math.ceil(len(text) / 4))


def format_usd(amount: float) -> str:
    """Format a USD amount for human-readable reports."""
    return f"${amount:,.6f}" if 0 < amount < 0.01 else f"${amount:,.2f}"


def percent(numerator: float, denominator: float) -> float:
    """Percentage helper that avoids division by zero."""
    if denominator == 0:
        return 0.0
    return round((numerator / denominator) * 100, 2)
