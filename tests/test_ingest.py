"""Knowledge ingestion: validation, deduplication, files, and collections."""

from __future__ import annotations

from pathlib import Path

import pytest

from agentforge.db import Database
from agentforge.errors import InvalidRequestError, NotFoundError
from agentforge.models import Classification
from agentforge.rag.ingest import KnowledgeBase


@pytest.fixture()
def knowledge() -> KnowledgeBase:
    db = Database(":memory:")
    instance = KnowledgeBase(db, target_chars=200, overlap_chars=40)
    try:
        yield instance
    finally:
        db.close()


def test_ingest_document_creates_chunks_and_metadata(knowledge: KnowledgeBase) -> None:
    content = "The concentration limit is 5% for a single issuer. " * 20
    result = knowledge.ingest_document(
        collection="research",
        title="Concentration Policy",
        content=content,
        source="concentration.md",
        classification=Classification.INTERNAL,
        metadata={"region": "canada"},
    )
    assert result.duplicate is False
    assert result.chunks_created > 1
    assert result.document.id.startswith("doc_")
    assert result.document.title == "Concentration Policy"
    assert knowledge.count_documents() == 1
    assert knowledge.collections() == ["research"]
    assert knowledge.stats()[0].chunks == result.chunks_created


def test_duplicate_documents_are_skipped(knowledge: KnowledgeBase) -> None:
    first = knowledge.ingest_document(
        collection="research", title="Policy", content="Identical policy text."
    )
    second = knowledge.ingest_document(
        collection="research", title="Different title", content="Identical policy text."
    )
    assert second.duplicate is True
    assert second.document.id == first.document.id
    assert second.chunks_created == 0
    assert knowledge.count_documents() == 1


def test_same_content_in_another_collection_is_distinct(knowledge: KnowledgeBase) -> None:
    first = knowledge.ingest_document(
        collection="research", title="Policy", content="Identical policy text."
    )
    second = knowledge.ingest_document(
        collection="client-policy", title="Policy", content="Identical policy text."
    )
    assert first.document.id != second.document.id
    assert knowledge.count_documents() == 2


def test_validation_errors(knowledge: KnowledgeBase) -> None:
    with pytest.raises(InvalidRequestError, match="Collection names"):
        knowledge.ingest_document(collection="Bad Name", title="T", content="body")
    with pytest.raises(InvalidRequestError, match="cannot be empty"):
        knowledge.ingest_document(collection="research", title="T", content="   ")
    with pytest.raises(InvalidRequestError, match="Invalid classification"):
        knowledge.ingest_document(
            collection="research", title="T", content="body", classification="secret"
        )
    with pytest.raises(InvalidRequestError, match="query"):
        knowledge.search("   ")


def test_ingest_file_extracts_markdown_title(knowledge: KnowledgeBase, tmp_path: Path) -> None:
    path = tmp_path / "policy.md"
    path.write_text("# Model Risk Standard\n\nHuman review is required.", encoding="utf-8")
    result = knowledge.ingest_file(path, collection="ai-governance")
    assert result.document.title == "Model Risk Standard"
    assert result.document.source == str(path)

    untitled = tmp_path / "service-levels.txt"
    untitled.write_text("No heading here, just service-level text.", encoding="utf-8")
    result = knowledge.ingest_file(untitled, collection="client-policy")
    assert result.document.title == "Service Levels"


def test_unsupported_file_type(knowledge: KnowledgeBase, tmp_path: Path) -> None:
    path = tmp_path / "data.csv"
    path.write_text("a,b", encoding="utf-8")
    with pytest.raises(InvalidRequestError, match="Unsupported file type"):
        knowledge.ingest_file(path, collection="research")


def test_ingest_directory_uses_subdirectories_as_collections(
    knowledge: KnowledgeBase, tmp_path: Path
) -> None:
    (tmp_path / "research").mkdir()
    (tmp_path / "research" / "a.md").write_text("# Policy A\n\nText A.", encoding="utf-8")
    (tmp_path / "Bad Dir").mkdir()
    (tmp_path / "Bad Dir" / "b.md").write_text("# Policy B\n\nText B.", encoding="utf-8")
    (tmp_path / "root.md").write_text("# Root\n\nRoot text.", encoding="utf-8")
    (tmp_path / "ignored.csv").write_text("a,b", encoding="utf-8")

    results = knowledge.ingest_directory(tmp_path)
    assert len(results) == 3
    assert set(knowledge.collections()) == {"research", "general"}

    with pytest.raises(NotFoundError):
        knowledge.ingest_directory(tmp_path / "missing")


def test_list_search_and_delete(knowledge: KnowledgeBase) -> None:
    result = knowledge.ingest_document(
        collection="research",
        title="Concentration",
        content="The maximum single issuer limit is five percent.",
    )
    documents = knowledge.list_documents()
    assert len(documents) == 1

    hits = knowledge.search("issuer limit", collections=["research"], top_k=2)
    assert hits
    assert hits[0].document_id == result.document.id

    knowledge.delete_document(result.document.id)
    assert knowledge.count_documents() == 0
    with pytest.raises(NotFoundError):
        knowledge.delete_document(result.document.id)
