"""SQLite-backed vector store with metadata and classification filtering."""

from __future__ import annotations

import json
import sqlite3
import struct
from collections.abc import Sequence
from typing import Any

from agentforge.db import Database
from agentforge.models import Chunk, Classification, CollectionStats, Document, RetrievedChunk
from agentforge.rag.embeddings import Embedder
from agentforge.util import safe_json_loads


def _pack(vector: Sequence[float]) -> bytes:
    return struct.pack(f"<{len(vector)}f", *vector)


def _unpack(blob: bytes) -> list[float]:
    count = len(blob) // 4
    return list(struct.unpack(f"<{count}f", blob))


class VectorStore:
    def __init__(self, db: Database, embedder: Embedder) -> None:
        self.db = db
        self.embedder = embedder

    # -- writes ---------------------------------------------------------
    def insert_document(
        self,
        document: Document,
        chunks: Sequence[Chunk],
        vectors: Sequence[Sequence[float]],
    ) -> None:
        if len(chunks) != len(vectors):
            raise ValueError("chunks and vectors must have equal length")
        with self.db.transaction() as connection:
            connection.execute(
                """
                INSERT INTO documents
                    (id, collection, title, source, classification, metadata,
                     content_hash, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    document.id,
                    document.collection,
                    document.title,
                    document.source,
                    document.classification.value,
                    _json(document.metadata),
                    document.content_hash,
                    document.created_at,
                ),
            )
            for chunk, vector in zip(chunks, vectors, strict=True):
                connection.execute(
                    """
                    INSERT INTO chunks
                        (id, document_id, collection, ordinal, content, token_estimate, metadata)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        chunk.id,
                        chunk.document_id,
                        chunk.collection,
                        chunk.ordinal,
                        chunk.content,
                        chunk.token_estimate,
                        _json(chunk.metadata),
                    ),
                )
                connection.execute(
                    "INSERT INTO embeddings "
                    "(chunk_id, model, dimension, vector) VALUES (?, ?, ?, ?)",
                    (chunk.id, self.embedder.name, len(vector), _pack(vector)),
                )

    def delete_document(self, document_id: str) -> bool:
        cursor = self.db.execute("DELETE FROM documents WHERE id = ?", (document_id,))
        return cursor.rowcount > 0

    # -- reads ----------------------------------------------------------
    def get_document(self, document_id: str) -> Document | None:
        row = self.db.query_one(
            """
            SELECT d.*,
                   (SELECT COUNT(*) FROM chunks c WHERE c.document_id = d.id) AS chunk_count
            FROM documents d WHERE d.id = ?
            """,
            (document_id,),
        )
        return _row_to_document(row) if row else None

    def find_document(self, collection: str, content_hash: str) -> Document | None:
        row = self.db.query_one(
            """
            SELECT d.*, (SELECT COUNT(*) FROM chunks c WHERE c.document_id = d.id) AS chunk_count
            FROM documents d WHERE d.collection = ? AND d.content_hash = ?
            """,
            (collection, content_hash),
        )
        return _row_to_document(row) if row else None

    def list_documents(self, collection: str | None = None) -> list[Document]:
        if collection:
            rows = self.db.query(
                """
                SELECT d.*,
                       (SELECT COUNT(*) FROM chunks c
                        WHERE c.document_id = d.id) AS chunk_count
                FROM documents d WHERE d.collection = ? ORDER BY d.created_at ASC
                """,
                (collection,),
            )
        else:
            rows = self.db.query(
                """
                SELECT d.*,
                       (SELECT COUNT(*) FROM chunks c
                        WHERE c.document_id = d.id) AS chunk_count
                FROM documents d ORDER BY d.created_at ASC
                """
            )
        return [_row_to_document(row) for row in rows]

    def count_documents(self, collection: str | None = None) -> int:
        if collection:
            return int(
                self.db.scalar(
                    "SELECT COUNT(*) FROM documents WHERE collection = ?", (collection,), 0
                )
            )
        return int(self.db.scalar("SELECT COUNT(*) FROM documents", default=0))

    def stats(self) -> list[CollectionStats]:
        rows = self.db.query(
            """
            SELECT d.collection AS collection,
                   COUNT(DISTINCT d.id) AS documents,
                   COUNT(c.id) AS chunks
            FROM documents d LEFT JOIN chunks c ON c.document_id = d.id
            GROUP BY d.collection ORDER BY d.collection
            """
        )
        result: list[CollectionStats] = []
        for row in rows:
            classification_rows = self.db.query(
                "SELECT classification, COUNT(*) AS count FROM documents "
                "WHERE collection = ? GROUP BY classification",
                (row["collection"],),
            )
            result.append(
                CollectionStats(
                    collection=row["collection"],
                    documents=int(row["documents"]),
                    chunks=int(row["chunks"]),
                    classifications={
                        item["classification"]: int(item["count"]) for item in classification_rows
                    },
                )
            )
        return result

    def list_chunks(
        self,
        collection: str,
        allowed: set[Classification],
        filters: dict[str, Any] | None = None,
    ) -> list[RetrievedChunk]:
        if not allowed:
            return []
        placeholders = ",".join("?" for _ in allowed)
        rows = self.db.query(
            f"""
            SELECT c.*, d.title, d.classification, d.metadata AS doc_metadata
            FROM chunks c JOIN documents d ON d.id = c.document_id
            WHERE c.collection = ? AND d.classification IN ({placeholders})
            """,
            (collection, *(item.value for item in allowed)),
        )
        return [
            _row_to_chunk(row, vector_score=0.0) for row in rows if _metadata_matches(row, filters)
        ]

    def search(
        self,
        collection: str,
        query: str,
        top_k: int = 10,
        allowed: set[Classification] | None = None,
        filters: dict[str, Any] | None = None,
    ) -> list[RetrievedChunk]:
        allowed = set(Classification) if allowed is None else allowed
        if not allowed:
            return []
        query_vector = self.embedder.embed(query)
        if not any(query_vector):
            return []
        placeholders = ",".join("?" for _ in allowed)
        rows = self.db.query(
            f"""
            SELECT c.*, d.title, d.classification, d.metadata AS doc_metadata, e.vector
            FROM chunks c
            JOIN documents d ON d.id = c.document_id
            JOIN embeddings e ON e.chunk_id = c.id
            WHERE c.collection = ? AND d.classification IN ({placeholders})
            """,
            (collection, *(item.value for item in allowed)),
        )
        scored: list[RetrievedChunk] = []
        for row in rows:
            if not _metadata_matches(row, filters):
                continue
            vector = _unpack(row["vector"])
            if len(vector) != len(query_vector):
                continue
            similarity = sum(a * b for a, b in zip(vector, query_vector, strict=True))
            if similarity <= 0:
                continue
            scored.append(_row_to_chunk(row, vector_score=similarity, score=similarity))
        scored.sort(key=lambda item: item.score, reverse=True)
        return scored[: max(1, top_k)]


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, default=str)


def _metadata_matches(row: sqlite3.Row, filters: dict[str, Any] | None) -> bool:
    if not filters:
        return True
    metadata = safe_json_loads(row["doc_metadata"], {})
    metadata.update(safe_json_loads(row["metadata"], {}))
    return all(metadata.get(key) == value for key, value in filters.items())


def _row_to_document(row: sqlite3.Row) -> Document:
    return Document(
        id=row["id"],
        collection=row["collection"],
        title=row["title"],
        source=row["source"],
        classification=Classification(row["classification"]),
        metadata=safe_json_loads(row["metadata"], {}),
        content_hash=row["content_hash"],
        created_at=row["created_at"],
        chunk_count=int(row["chunk_count"]) if "chunk_count" in row.keys() else 0,  # noqa: SIM118
    )


def _row_to_chunk(
    row: sqlite3.Row,
    *,
    vector_score: float,
    score: float | None = None,
) -> RetrievedChunk:
    metadata = safe_json_loads(row["doc_metadata"], {})
    metadata.update(safe_json_loads(row["metadata"], {}))
    return RetrievedChunk(
        chunk_id=row["id"],
        document_id=row["document_id"],
        collection=row["collection"],
        title=row["title"],
        content=row["content"],
        classification=Classification(row["classification"]),
        score=vector_score if score is None else score,
        vector_score=vector_score,
        metadata=metadata,
    )
