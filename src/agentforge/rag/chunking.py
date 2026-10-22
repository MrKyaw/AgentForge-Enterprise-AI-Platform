"""Deterministic, boundary-aware text chunking."""

from __future__ import annotations

import re

_WHITESPACE = re.compile(r"[ \t]+")


def _normalize(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [_WHITESPACE.sub(" ", line).strip() for line in text.split("\n")]
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _find_break(text: str, start: int, end: int) -> int:
    """Find a pleasant cut point between 55% and 100% of the target window."""
    floor = start + int((end - start) * 0.55)
    for separator, include in (("\n\n", 0), (". ", 1), ("\n", 0), ("; ", 1), (" ", 0)):
        index = text.rfind(separator, floor, end)
        if index != -1:
            return index + include
    return end


def chunk_text(
    text: str,
    target_chars: int = 700,
    overlap_chars: int = 120,
) -> list[str]:
    """Split text into overlapping chunks without cutting words.

    The chunker prefers paragraph and sentence boundaries, which makes
    citations readable and keeps source attribution stable.
    """
    if target_chars < 80:
        raise ValueError("target_chars must be >= 80")
    if overlap_chars < 0 or overlap_chars >= target_chars:
        raise ValueError("overlap_chars must be >= 0 and < target_chars")
    normalized = _normalize(text)
    if not normalized:
        return []
    if len(normalized) <= target_chars:
        return [normalized]

    chunks: list[str] = []
    start = 0
    length = len(normalized)
    while start < length:
        end = min(start + target_chars, length)
        if end < length:
            end = max(start + 1, _find_break(normalized, start, end))
        chunk = normalized[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= length:
            break
        next_start = max(start + 1, end - overlap_chars)
        while next_start < end and not normalized[next_start - 1].isspace():
            next_start += 1
        start = next_start if next_start > start else end
    return chunks


def chunk_markdown(
    text: str,
    target_chars: int = 700,
    overlap_chars: int = 120,
) -> list[str]:
    """Alias retained for callers that want to signal markdown input."""
    return chunk_text(text, target_chars=target_chars, overlap_chars=overlap_chars)
