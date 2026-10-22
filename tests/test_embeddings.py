"""Deterministic hashing embeddings."""

from __future__ import annotations

import math

import pytest

from agentforge.rag.embeddings import HashingEmbedder


def test_dimension_validation() -> None:
    with pytest.raises(ValueError, match="dimension"):
        HashingEmbedder(dimension=16)
    embedder = HashingEmbedder(dimension=64)
    assert embedder.dimension == 64
    assert embedder.name == "hashing-64"


def test_embeddings_are_deterministic_and_normalized() -> None:
    embedder = HashingEmbedder(dimension=128)
    first = embedder.embed("single issuer concentration limit")
    second = embedder.embed("single issuer concentration limit")
    assert first == second
    assert len(first) == 128
    assert pytest.approx(math.sqrt(sum(value * value for value in first))) == 1.0


def test_similar_text_scores_higher_than_unrelated_text() -> None:
    embedder = HashingEmbedder(dimension=256)
    query = embedder.embed("maximum single issuer concentration limit")
    related = embedder.embed("the maximum single issuer limit is five percent")
    unrelated = embedder.embed("client complaint acknowledgement service standard")
    assert embedder.cosine(query, related) > embedder.cosine(query, unrelated)


def test_empty_text_yields_zero_vector() -> None:
    embedder = HashingEmbedder(dimension=32)
    vector = embedder.embed("")
    assert vector == [0.0] * 32


def test_embed_many_matches_individual_calls() -> None:
    embedder = HashingEmbedder(dimension=64)
    texts = ["alpha policy", "beta standard", ""]
    assert embedder.embed_many(texts) == [embedder.embed(text) for text in texts]


def test_cosine_requires_equal_dimensions() -> None:
    with pytest.raises(ValueError, match="same dimension"):
        HashingEmbedder.cosine([1.0], [1.0, 2.0])
    assert HashingEmbedder.cosine([1.0, 0.0], [1.0, 0.0]) == 1.0
