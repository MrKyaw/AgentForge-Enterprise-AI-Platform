"""BM25 lexical ranking."""

from __future__ import annotations

from agentforge.models import Classification, RetrievedChunk
from agentforge.rag.bm25 import BM25Index


def _chunk(chunk_id: str, content: str) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        document_id=f"doc_{chunk_id}",
        collection="research",
        title=chunk_id,
        content=content,
        classification=Classification.INTERNAL,
        score=0.0,
    )


def test_ranks_matching_document_first() -> None:
    index = BM25Index(
        [
            _chunk("a", "The maximum single issuer concentration limit is 5%."),
            _chunk("b", "Client complaints are acknowledged within two business days."),
            _chunk("c", "Model risk reviews happen every quarter."),
        ]
    )
    hits = index.search("single issuer concentration limit", top_k=2)
    assert hits[0].chunk_id == "a"
    assert hits[0].score > 0
    assert all(hit.score > 0 for hit in hits)


def test_unmatched_terms_return_no_hits() -> None:
    index = BM25Index([_chunk("a", "alpha beta gamma")])
    assert index.search("delta epsilon") == []


def test_empty_query_and_empty_corpus() -> None:
    assert BM25Index([]).search("anything") == []
    assert BM25Index([_chunk("a", "alpha")]).search("") == []


def test_top_k_is_clamped_and_ordered() -> None:
    index = BM25Index(
        [
            _chunk("a", "policy policy policy"),
            _chunk("b", "policy once"),
            _chunk("c", "unrelated text"),
        ]
    )
    hits = index.search("policy", top_k=10)
    assert len(hits) == 2
    assert hits[0].chunk_id == "a"
    assert hits[0].score >= hits[1].score
    assert len(index.search("policy", top_k=0)) == 1
