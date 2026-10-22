"""Compact BM25 implementation for hybrid retrieval."""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from agentforge.models import RetrievedChunk
from agentforge.util import tokenize


@dataclass(slots=True)
class BM25Hit:
    chunk_id: str
    score: float


class BM25Index:
    def __init__(
        self,
        documents: Sequence[RetrievedChunk],
        k1: float = 1.5,
        b: float = 0.75,
    ) -> None:
        self.documents = list(documents)
        self.k1 = k1
        self.b = b
        self._tokens: list[list[str]] = [tokenize(doc.content) for doc in self.documents]
        self._lengths = [len(tokens) for tokens in self._tokens]
        self._avg_length = (sum(self._lengths) / len(self._lengths)) if self._lengths else 0.0
        self._document_frequency: Counter[str] = Counter()
        for tokens in self._tokens:
            self._document_frequency.update(set(tokens))
        self._count = len(self.documents)

    def _idf(self, term: str) -> float:
        frequency = self._document_frequency.get(term, 0)
        return math.log(1.0 + (self._count - frequency + 0.5) / (frequency + 0.5))

    def _score(self, query_terms: Iterable[str], index: int) -> float:
        tokens = self._tokens[index]
        if not tokens:
            return 0.0
        counts = Counter(tokens)
        length = self._lengths[index]
        score = 0.0
        for term in query_terms:
            frequency = counts.get(term, 0)
            if frequency == 0:
                continue
            denominator = frequency + self.k1 * (
                1.0 - self.b + self.b * (length / self._avg_length if self._avg_length else 0.0)
            )
            score += self._idf(term) * (frequency * (self.k1 + 1.0)) / denominator
        return score

    def search(self, query: str, top_k: int = 10) -> list[BM25Hit]:
        terms = tokenize(query)
        if not terms or not self.documents:
            return []
        scored = [
            BM25Hit(chunk_id=self.documents[index].chunk_id, score=self._score(terms, index))
            for index in range(self._count)
        ]
        scored = [hit for hit in scored if hit.score > 0]
        scored.sort(key=lambda hit: hit.score, reverse=True)
        return scored[: max(1, top_k)]
