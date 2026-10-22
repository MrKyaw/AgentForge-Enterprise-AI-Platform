"""Request and response schemas unique to the HTTP surface."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from agentforge.models import Approval, Classification, RunResult


class IngestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    collection: str = Field(min_length=2, max_length=41)
    title: str = Field(min_length=1, max_length=300)
    content: str = Field(min_length=1, max_length=500_000)
    source: str = Field(default="", max_length=1000)
    classification: Classification = Classification.INTERNAL
    metadata: dict[str, Any] = Field(default_factory=dict)


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=2000)
    collections: list[str] | None = None
    top_k: int = Field(default=4, ge=1, le=20)
    filters: dict[str, Any] = Field(default_factory=dict)


class ApprovalDecisionResponse(BaseModel):
    approval: Approval
    run: RunResult


class EvalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tags: list[str] = Field(default_factory=list)


class DeleteResponse(BaseModel):
    deleted: bool
    id: str
