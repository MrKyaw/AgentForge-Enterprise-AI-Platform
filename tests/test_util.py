"""Utilities underpin IDs, hashing, tokenization, and formatting."""

from __future__ import annotations

import json
import re

from agentforge.util import (
    canonical_json,
    clip,
    content_tokens,
    estimate_tokens,
    format_usd,
    new_id,
    normalize_whitespace,
    now_iso,
    percent,
    safe_json_loads,
    sha256_text,
    today_utc,
    tokenize,
)


def test_timestamps_are_utc_iso() -> None:
    stamp = now_iso()
    assert stamp.endswith("Z")
    assert "T" in stamp
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", today_utc())


def test_new_id_is_prefixed_and_unique() -> None:
    first = new_id("run")
    second = new_id("run")
    assert first.startswith("run_")
    assert len(first) == len("run_") + 16
    assert first != second
    assert len(new_id("x", 4)) == 6


def test_sha256_and_canonical_json_are_stable() -> None:
    assert sha256_text("abc") == sha256_text("abc")
    assert sha256_text("abc") != sha256_text("abcd")
    left = canonical_json({"b": 2, "a": 1})
    right = canonical_json({"a": 1, "b": 2})
    assert left == right == '{"a":1,"b":2}'
    assert json.loads(left) == {"a": 1, "b": 2}
    assert canonical_json({"when": object})  # default=str keeps hashing total


def test_safe_json_loads_falls_back() -> None:
    assert safe_json_loads('{"a": 1}') == {"a": 1}
    assert safe_json_loads("not-json", {"safe": True}) == {"safe": True}
    assert safe_json_loads("", "empty") == "empty"
    assert safe_json_loads(None) is None


def test_tokenizer_stems_plurals_and_preserves_numbers() -> None:
    assert tokenize("Policies and 5% returns") == ["policy", "and", "5%", "return"]
    assert tokenize("address") == ["address"]  # ends with ss, left intact
    assert tokenize("companies") == ["company"]
    assert tokenize("") == []


def test_content_tokens_remove_stopwords() -> None:
    tokens = content_tokens("The policy is in the approved knowledge base")
    assert "the" not in tokens
    assert "is" not in tokens
    assert "policy" in tokens


def test_normalize_whitespace_collapses_runs() -> None:
    assert normalize_whitespace("  a \n\t b   c ") == "a b c"
    assert normalize_whitespace("") == ""


def test_clip_respects_word_boundaries() -> None:
    text = "The quick brown fox jumps over the lazy dog"
    assert clip(text, 100) == text
    clipped = clip(text, 20)
    assert len(clipped) <= 20
    assert clipped.endswith("…")
    assert clip("abcdefghij", 3) == "ab…"
    assert clip("abcdefghij", 1) == "a"
    assert clip("short", 5, suffix="...") == "short"


def test_estimate_tokens_is_never_zero() -> None:
    assert estimate_tokens("") == 1
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("a" * 9) == 3


def test_format_usd_switches_precision() -> None:
    assert format_usd(0) == "$0.00"
    assert format_usd(1.2345) == "$1.23"
    assert format_usd(0.0042) == "$0.004200"


def test_percent_handles_zero_denominator() -> None:
    assert percent(1, 4) == 25.0
    assert percent(0, 0) == 0.0
    assert percent(1, 3) == 33.33
