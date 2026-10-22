"""Hybrid retrieval fuses vector and BM25 rankings."""

from __future__ import annotations

from agentforge.db import Database
from agentforge.models import Chunk, Classification, Document
from agentforge.rag.embeddings import HashingEmbedder
from agentforge.rag.retriever import HybridRetriever
from agentforge.rag.store import VectorStore


def _seed_store(db: Database) -> VectorStore:
    embedder = HashingEmbedder(dimension=256)
    store = VectorStore(db, embedder)
    corpus = {
        "doc_research": (
            "research",
            "Concentration Standard",
            [
                "The maximum single issuer concentration limit is five percent.",
                "A position above four and a half percent must be reviewed.",
            ],
        ),
        "doc_client": (
            "client-policy",
            "Service Standard",
            [
                "A client complaint must be acknowledged within two business days.",
                "Complaints are resolved within ten business days.",
            ],
        ),
    }
    for document_id, (collection, title, contents) in corpus.items():
        document = Document(
            id=document_id,
            collection=collection,
            title=title,
            classification=Classification.INTERNAL,
            content_hash=f"hash-{document_id}",
            created_at="2026-01-01T00:00:00Z",
        )
        chunks = [
            Chunk(
                id=f"{document_id}_chk_{index}",
                document_id=document_id,
                collection=collection,
                ordinal=index,
                content=content,
                token_estimate=max(1, len(content) // 4),
            )
            for index, content in enumerate(contents)
        ]
        store.insert_document(document, chunks, embedder.embed_many(contents))
    return store


def test_hybrid_search_returns_ranked_hits() -> None:
    db = Database(":memory:")
    try:
        retriever = HybridRetriever(_seed_store(db))
        hits = retriever.search(
            "single issuer concentration limit",
            ["research", "client-policy"],
            top_k=3,
        )
        assert hits
        assert hits[0].collection == "research"
        assert hits[0].score > 0
        assert hits[0].vector_score > 0
        assert hits[0].keyword_score > 0
    finally:
        db.close()


def test_keyword_only_matches_still_rank() -> None:
    db = Database(":memory:")
    try:
        retriever = HybridRetriever(_seed_store(db))
        hits = retriever.search("complaint acknowledged", ["client-policy"], top_k=2)
        assert hits
        assert hits[0].keyword_score > 0
        assert len(hits) <= 2
    finally:
        db.close()


def test_collection_and_clearance_filters() -> None:
    db = Database(":memory:")
    try:
        retriever = HybridRetriever(_seed_store(db))
        assert retriever.search("issuer", ["missing"], top_k=2) == []
        assert (
            retriever.search(
                "issuer",
                ["research"],
                top_k=2,
                allowed={Classification.RESTRICTED},
            )
            == []
        )
        assert retriever.search("issuer", ["research"], top_k=2, filters={"nope": 1}) == []
    finally:
        db.close()


def test_top_k_is_bounded() -> None:
    db = Database(":memory:")
    try:
        retriever = HybridRetriever(_seed_store(db))
        hits = retriever.search("business days", ["client-policy"], top_k=100)
        assert len(hits) == 2
        assert len(retriever.search("business days", ["client-policy"], top_k=0)) == 1
    finally:
        db.close()
