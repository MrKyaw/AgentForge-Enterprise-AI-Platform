"""Hybrid dense + lexical retrieval fused with reciprocal rank fusion (RRF)."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from agentforge.models import Classification, RetrievedChunk
from agentforge.rag.bm25 import BM25Index
from agentforge.rag.store import VectorStore


class HybridRetriever:
    def __init__(self, store: VectorStore, rrf_constant: int = 60) -> None:
        self.store = store
        self.rrf_constant = rrf_constant

    def search(
        self,
        query: str,
        collections: Iterable[str],
        *,
        top_k: int = 4,
        allowed: set[Classification] | None = None,
        filters: dict[str, Any] | None = None,
    ) -> list[RetrievedChunk]:
        allowed = set(Classification) if allowed is None else allowed
        top_k = max(1, min(top_k, 20))
        candidates: dict[str, RetrievedChunk] = {}
        vector_rankings: list[list[str]] = []
        for collection in collections:
            chunks = self.store.list_chunks(collection, allowed, filters)
            for chunk in chunks:
                candidates.setdefault(chunk.chunk_id, chunk)
            hits = self.store.search(
                collection,
                query,
                top_k=top_k * 4,
                allowed=allowed,
                filters=filters,
            )
            if hits:
                vector_rankings.append([hit.chunk_id for hit in hits])
                for hit in hits:
                    if hit.chunk_id in candidates:
                        candidates[hit.chunk_id].vector_score = hit.vector_score

        if not candidates:
            return []

        bm25 = BM25Index(list(candidates.values()))
        keyword_hits = bm25.search(query, top_k=top_k * 4)
        keyword_scores = {hit.chunk_id: hit.score for hit in keyword_hits}
        keyword_ranking = [hit.chunk_id for hit in keyword_hits]

        fused: dict[str, float] = {}
        for ranking in vector_rankings:
            for rank, chunk_id in enumerate(ranking):
                fused[chunk_id] = fused.get(chunk_id, 0.0) + 1.0 / (self.rrf_constant + rank + 1)
        for rank, chunk_id in enumerate(keyword_ranking):
            fused[chunk_id] = fused.get(chunk_id, 0.0) + 1.0 / (self.rrf_constant + rank + 1)

        results: list[RetrievedChunk] = []
        for chunk_id, fused_score in fused.items():
            chunk = candidates[chunk_id]
            chunk.keyword_score = round(keyword_scores.get(chunk_id, 0.0), 6)
            chunk.score = round(fused_score, 8)
            results.append(chunk)
        results.sort(key=lambda item: item.score, reverse=True)
        return results[:top_k]
