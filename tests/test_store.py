"""Vector store persistence, filtering, and similarity search."""

from __future__ import annotations

import pytest

from agentforge.db import Database
from agentforge.models import Chunk, Classification, Document
from agentforge.rag.embeddings import HashingEmbedder
from agentforge.rag.store import VectorStore


@pytest.fixture()
def store() -> VectorStore:
    db = Database(":memory:")
    embedder = HashingEmbedder(dimension=128)
    instance = VectorStore(db, embedder)
    document = Document(
        id="doc_1",
        collection="research",
        title="Concentration Policy",
        source="policy.md",
        classification=Classification.INTERNAL,
        metadata={"region": "canada"},
        content_hash="hash-1",
        created_at="2026-01-01T00:00:00Z",
        chunk_count=2,
    )
    chunks = [
        Chunk(
            id="chk_1",
            document_id="doc_1",
            collection="research",
            ordinal=0,
            content="The maximum single issuer concentration limit is five percent.",
            token_estimate=12,
            metadata={"section": "limits"},
        ),
        Chunk(
            id="chk_2",
            document_id="doc_1",
            collection="research",
            ordinal=1,
            content="Client complaints are acknowledged within two business days.",
            token_estimate=12,
            metadata={"section": "service"},
        ),
    ]
    vectors = embedder.embed_many([chunk.content for chunk in chunks])
    instance.insert_document(document, chunks, vectors)
    try:
        yield instance
    finally:
        db.close()


def test_reads_documents_and_counts(store: VectorStore) -> None:
    document = store.get_document("doc_1")
    assert document is not None
    assert document.title == "Concentration Policy"
    assert document.chunk_count == 2
    assert document.metadata == {"region": "canada"}
    assert store.get_document("missing") is None
    assert store.find_document("research", "hash-1") is not None
    assert store.find_document("research", "other") is None
    assert store.count_documents() == 1
    assert store.count_documents("research") == 1
    assert store.count_documents("missing") == 0
    assert len(store.list_documents()) == 1
    assert len(store.list_documents("research")) == 1
    assert store.list_documents("missing") == []


def test_stats_include_classification_breakdown(store: VectorStore) -> None:
    stats = store.stats()
    assert len(stats) == 1
    assert stats[0].collection == "research"
    assert stats[0].documents == 1
    assert stats[0].chunks == 2
    assert stats[0].classifications == {"internal": 1}


def test_similarity_search(store: VectorStore) -> None:
    hits = store.search("research", "single issuer concentration limit", top_k=2)
    assert hits
    assert hits[0].chunk_id == "chk_1"
    assert hits[0].vector_score > 0
    assert hits[0].score == hits[0].vector_score
    assert hits[0].metadata["section"] == "limits"
    assert hits[0].metadata["region"] == "canada"
    assert store.search("research", "!!!", top_k=2) == []
    assert store.search("research", "issuer", top_k=2, allowed=set()) == []


def test_classification_filtering(store: VectorStore) -> None:
    assert store.search(
        "research", "single issuer concentration limit", allowed={Classification.INTERNAL}
    )
    assert (
        store.search(
            "research", "single issuer concentration limit", allowed={Classification.RESTRICTED}
        )
        == []
    )
    assert store.list_chunks("research", {Classification.PUBLIC}) == []
    assert len(store.list_chunks("research", {Classification.INTERNAL})) == 2


def test_metadata_filtering(store: VectorStore) -> None:
    assert (
        len(
            store.search(
                "research", "single issuer concentration limit", filters={"region": "canada"}
            )
        )
        == 1
    )
    assert (
        store.search("research", "single issuer concentration limit", filters={"region": "usa"})
        == []
    )
    assert (
        len(store.list_chunks("research", {Classification.INTERNAL}, {"section": "service"})) == 1
    )


def test_delete_cascades(store: VectorStore) -> None:
    assert store.delete_document("missing") is False
    assert store.delete_document("doc_1") is True
    assert store.get_document("doc_1") is None
    assert store.db.scalar("SELECT COUNT(*) FROM chunks") == 0
    assert store.db.scalar("SELECT COUNT(*) FROM embeddings") == 0


def test_mismatched_chunks_and_vectors_are_rejected(store: VectorStore) -> None:
    document = Document(
        id="doc_2",
        collection="research",
        title="Bad",
        content_hash="hash-2",
        created_at="2026-01-01T00:00:00Z",
    )
    chunk = Chunk(
        id="chk_3",
        document_id="doc_2",
        collection="research",
        ordinal=0,
        content="text",
        token_estimate=1,
    )
    with pytest.raises(ValueError, match="equal length"):
        store.insert_document(document, [chunk], [])
