"""Deterministic local embeddings.

The built-in embedder uses feature hashing over unigrams and bigrams. It needs
no model download, is stable across processes, and is good enough for keyword-
rich enterprise documents. Production deployments can inject a hosted embedder
through the same ``Embedder`` protocol.
"""

from __future__ import annotations

import hashlib
import math
from collections import Counter
from collections.abc import Sequence
from itertools import pairwise
from typing import Protocol

from agentforge.util import tokenize


class Embedder(Protocol):
    name: str
    dimension: int

    def embed(self, text: str) -> list[float]: ...

    def embed_many(self, texts: Sequence[str]) -> list[list[float]]: ...


class HashingEmbedder:
    """Feature-hashing embedder with sublinear term frequency and L2 normalization."""

    def __init__(self, dimension: int = 384) -> None:
        if dimension < 32:
            raise ValueError("dimension must be >= 32")
        self.dimension = dimension
        self.name = f"hashing-{dimension}"

    def _bucket(self, feature: str) -> tuple[int, float]:
        digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
        index = int.from_bytes(digest[:4], "little") % self.dimension
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        return index, sign

    def embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimension
        tokens = tokenize(text)
        if not tokens:
            return vector
        frequencies = Counter(tokens)
        for token, count in frequencies.items():
            index, sign = self._bucket(token)
            vector[index] += sign * (1.0 + math.log(count))
        for first, second in pairwise(tokens):
            index, sign = self._bucket(f"{first} {second}")
            vector[index] += sign * 0.5
        norm = math.sqrt(sum(value * value for value in vector))
        if norm > 0:
            vector = [value / norm for value in vector]
        return vector

    def embed_many(self, texts: Sequence[str]) -> list[list[float]]:
        return [self.embed(text) for text in texts]

    @staticmethod
    def cosine(left: Sequence[float], right: Sequence[float]) -> float:
        if len(left) != len(right):
            raise ValueError("vectors must have the same dimension")
        return sum(a * b for a, b in zip(left, right, strict=True))
