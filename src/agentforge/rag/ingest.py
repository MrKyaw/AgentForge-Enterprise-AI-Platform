"""Document ingestion, deduplication, and collection management."""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from agentforge.db import Database
from agentforge.errors import InvalidRequestError, NotFoundError
from agentforge.models import (
    Chunk,
    Classification,
    Document,
    IngestResult,
    RetrievedChunk,
)
from agentforge.rag.chunking import chunk_text
from agentforge.rag.embeddings import Embedder, HashingEmbedder
from agentforge.rag.retriever import HybridRetriever
from agentforge.rag.store import VectorStore
from agentforge.util import estimate_tokens, now_iso, sha256_text

COLLECTION_RE = re.compile(r"^[a-z][a-z0-9-]{1,40}$")
SUPPORTED_EXTENSIONS = frozenset({".md", ".txt"})


class KnowledgeBase:
    def __init__(
        self,
        db: Database,
        embedder: Embedder | None = None,
        *,
        target_chars: int = 700,
        overlap_chars: int = 120,
    ) -> None:
        self.db = db
        self.embedder = embedder or HashingEmbedder()
        self.store = VectorStore(db, self.embedder)
        self.retriever = HybridRetriever(self.store)
        self.target_chars = target_chars
        self.overlap_chars = overlap_chars

    def ingest_document(
        self,
        *,
        collection: str,
        title: str,
        content: str,
        source: str = "",
        classification: Classification | str = Classification.INTERNAL,
        metadata: dict[str, Any] | None = None,
    ) -> IngestResult:
        self._validate_collection(collection)
        if not content or not content.strip():
            raise InvalidRequestError("Document content cannot be empty.")
        title = title.strip() or "Untitled document"
        try:
            level = Classification(classification)
        except ValueError as exc:
            raise InvalidRequestError(
                f"Invalid classification '{classification}'. "
                "Expected public, internal, confidential, or restricted."
            ) from exc
        content_hash = sha256_text(content)
        existing = self.store.find_document(collection, content_hash)
        if existing:
            return IngestResult(document=existing, duplicate=True, chunks_created=0)

        document_id = f"doc_{sha256_text(f'{collection}:{content_hash}')[:20]}"
        pieces = chunk_text(
            content,
            target_chars=self.target_chars,
            overlap_chars=self.overlap_chars,
        )
        if not pieces:
            raise InvalidRequestError("Document produced no chunks.")
        chunks = [
            Chunk(
                id=f"chk_{sha256_text(f'{document_id}:{index}')[:20]}",
                document_id=document_id,
                collection=collection,
                ordinal=index,
                content=piece,
                token_estimate=estimate_tokens(piece),
            )
            for index, piece in enumerate(pieces)
        ]
        vectors = self.embedder.embed_many([chunk.content for chunk in chunks])
        document = Document(
            id=document_id,
            collection=collection,
            title=title,
            source=source,
            classification=level,
            metadata=metadata or {},
            content_hash=content_hash,
            created_at=now_iso(),
            chunk_count=len(chunks),
        )
        self.store.insert_document(document, chunks, vectors)
        return IngestResult(document=document, duplicate=False, chunks_created=len(chunks))

    def ingest_file(
        self,
        path: str | Path,
        *,
        collection: str,
        classification: Classification | str = Classification.INTERNAL,
        metadata: dict[str, Any] | None = None,
    ) -> IngestResult:
        file_path = Path(path)
        if file_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            raise InvalidRequestError(
                f"Unsupported file type '{file_path.suffix}'. "
                f"Supported: {sorted(SUPPORTED_EXTENSIONS)}."
            )
        content = file_path.read_text(encoding="utf-8")
        title = self._extract_title(content) or file_path.stem.replace("-", " ").title()
        return self.ingest_document(
            collection=collection,
            title=title,
            content=content,
            source=str(file_path),
            classification=classification,
            metadata=metadata,
        )

    def ingest_directory(
        self,
        root: str | Path,
        *,
        default_classification: Classification | str = Classification.INTERNAL,
    ) -> list[IngestResult]:
        """Ingest ``root/<collection>/*.md`` using the subdirectory as collection."""
        root_path = Path(root)
        if not root_path.exists():
            raise NotFoundError(f"Corpus directory not found: {root_path}")
        results: list[IngestResult] = []
        for path in sorted(root_path.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                continue
            relative = path.parent.relative_to(root_path)
            collection = relative.parts[0] if relative.parts else "general"
            if not COLLECTION_RE.match(collection):
                collection = "general"
            results.append(
                self.ingest_file(
                    path,
                    collection=collection,
                    classification=default_classification,
                    metadata={"path": str(path.relative_to(root_path))},
                )
            )
        return results

    def list_documents(self, collection: str | None = None) -> list[Document]:
        return self.store.list_documents(collection)

    def delete_document(self, document_id: str) -> None:
        if not self.store.delete_document(document_id):
            raise NotFoundError(f"Document not found: {document_id}")

    def stats(self):
        return self.store.stats()

    def count_documents(self) -> int:
        return self.store.count_documents()

    def collections(self) -> list[str]:
        return [item.collection for item in self.store.stats()]

    def search(
        self,
        query: str,
        *,
        collections: Iterable[str] | None = None,
        top_k: int = 4,
        allowed: set[Classification] | None = None,
        filters: dict[str, Any] | None = None,
    ) -> list[RetrievedChunk]:
        if not query.strip():
            raise InvalidRequestError("Search query cannot be empty.")
        selected = list(collections or self.collections())
        return self.retriever.search(
            query,
            selected,
            top_k=top_k,
            allowed=allowed,
            filters=filters,
        )

    @staticmethod
    def _validate_collection(collection: str) -> None:
        if not COLLECTION_RE.match(collection):
            raise InvalidRequestError(
                "Collection names must be 2-41 characters, start with a letter, "
                "and contain only lowercase letters, digits, and hyphens."
            )

    @staticmethod
    def _extract_title(content: str) -> str | None:
        for line in content.splitlines():
            if line.startswith("# "):
                return line[2:].strip()
        return None
