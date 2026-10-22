"""Boundary-aware chunking keeps content stable and readable."""

from __future__ import annotations

import pytest

from agentforge.rag.chunking import chunk_markdown, chunk_text


def test_short_text_is_a_single_chunk() -> None:
    assert chunk_text("A short policy note.") == ["A short policy note."]


def test_empty_and_whitespace_text_produce_nothing() -> None:
    assert chunk_text("") == []
    assert chunk_text("   \n\t  ") == []


def test_long_text_is_split_within_bounds() -> None:
    paragraph = "The policy requires documented reviews for every material exception. "
    text = "\n\n".join(paragraph * 4 for _ in range(20))
    chunks = chunk_text(text, target_chars=400, overlap_chars=60)
    assert len(chunks) > 3
    assert all(chunk.strip() for chunk in chunks)
    assert all(len(chunk) <= 400 for chunk in chunks)
    # Consecutive chunks overlap, preserving context across the boundary.
    assert chunks[0][-20:] in text
    assert chunks[0][-20:] in chunks[1]


def test_overlap_can_be_zero() -> None:
    text = " ".join(f"sentence {index} about governance." for index in range(200))
    chunks = chunk_text(text, target_chars=200, overlap_chars=0)
    assert len(chunks) > 1
    assert all(len(chunk) <= 200 for chunk in chunks)


def test_prefers_paragraph_and_sentence_boundaries() -> None:
    first = "First paragraph is here and it is long enough to end at a boundary."
    text = f"{first}\n\nSecond paragraph continues the policy text.\n\nThird one."
    chunks = chunk_text(text, target_chars=90, overlap_chars=0)
    assert chunks[0] == first


def test_normalizes_line_endings_and_spacing() -> None:
    text = "Line one   with   spaces\r\n\r\n\r\nLine two"
    chunks = chunk_text(text)
    assert chunks == ["Line one with spaces\n\nLine two"]


def test_validation_errors() -> None:
    with pytest.raises(ValueError, match="target_chars"):
        chunk_text("text", target_chars=40)
    with pytest.raises(ValueError, match="overlap_chars"):
        chunk_text("text", target_chars=100, overlap_chars=100)
    with pytest.raises(ValueError, match="overlap_chars"):
        chunk_text("text", target_chars=100, overlap_chars=-1)


def test_markdown_alias_matches_chunk_text() -> None:
    text = "## Heading\n\n" + "Policy sentence. " * 100
    assert chunk_markdown(text, target_chars=300, overlap_chars=50) == chunk_text(
        text, target_chars=300, overlap_chars=50
    )
