"""Knowledge ingestion, discovery, and hybrid search endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status

from agentforge.api.deps import get_admin, get_container, get_principal
from agentforge.api.schemas import DeleteResponse, IngestRequest, SearchRequest
from agentforge.bootstrap import Container
from agentforge.models import (
    CollectionStats,
    Document,
    IngestResult,
    Principal,
    RetrievedChunk,
)
from agentforge.security import allowed_classifications

router = APIRouter(prefix="/v1/knowledge", tags=["Knowledge"])


@router.get("/collections", response_model=list[CollectionStats], summary="List collections")
def list_collections(
    _principal: Principal = Depends(get_principal),
    container: Container = Depends(get_container),
) -> list[CollectionStats]:
    return container.knowledge.stats()


@router.get("/documents", response_model=list[Document], summary="List documents")
def list_documents(
    collection: str | None = Query(default=None),
    principal: Principal = Depends(get_principal),
    container: Container = Depends(get_container),
) -> list[Document]:
    visible = allowed_classifications(principal.role)
    documents = container.knowledge.list_documents(collection)
    return [document for document in documents if document.classification in visible]


@router.post(
    "/documents",
    response_model=IngestResult,
    status_code=status.HTTP_201_CREATED,
    summary="Ingest a document (admin)",
)
def ingest_document(
    body: IngestRequest,
    principal: Principal = Depends(get_admin),
    container: Container = Depends(get_container),
) -> IngestResult:
    result = container.knowledge.ingest_document(
        collection=body.collection,
        title=body.title,
        content=body.content,
        source=body.source,
        classification=body.classification,
        metadata=body.metadata,
    )
    if not result.duplicate:
        container.audit.record(
            "knowledge.document_ingested",
            tenant=principal.tenant,
            actor=principal.key_id,
            resource=result.document.id,
            payload={
                "collection": result.document.collection,
                "classification": result.document.classification.value,
                "chunks": result.chunks_created,
                "content_hash": result.document.content_hash,
            },
        )
    return result


@router.delete(
    "/documents/{document_id}",
    response_model=DeleteResponse,
    summary="Delete a document (admin)",
)
def delete_document(
    document_id: str,
    principal: Principal = Depends(get_admin),
    container: Container = Depends(get_container),
) -> DeleteResponse:
    container.knowledge.delete_document(document_id)
    container.audit.record(
        "knowledge.document_deleted",
        tenant=principal.tenant,
        actor=principal.key_id,
        resource=document_id,
    )
    return DeleteResponse(deleted=True, id=document_id)


@router.post(
    "/search",
    response_model=list[RetrievedChunk],
    summary="Hybrid vector + BM25 search",
)
def search(
    body: SearchRequest,
    principal: Principal = Depends(get_principal),
    container: Container = Depends(get_container),
) -> list[RetrievedChunk]:
    allowed = allowed_classifications(principal.role)
    return container.knowledge.search(
        body.query,
        collections=body.collections,
        top_k=body.top_k,
        allowed=allowed,
        filters=body.filters,
    )
