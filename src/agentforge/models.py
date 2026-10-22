"""Domain models shared by the API, runtime, and evaluation harness."""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from agentforge.util import new_id, now_iso


class Role(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class Classification(str, Enum):
    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Lifecycle(str, Enum):
    ACTIVE = "active"
    DRAFT = "draft"
    DEPRECATED = "deprecated"
    RETIRED = "retired"


class RunStatus(str, Enum):
    COMPLETED = "completed"
    PENDING_APPROVAL = "pending_approval"
    REJECTED = "rejected"
    APPROVAL_FAILED = "approval_failed"
    MAX_STEPS_EXCEEDED = "max_steps_exceeded"
    FAILED = "failed"


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    FAILED = "failed"


class ToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: new_id("call", 12))
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class Message(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Role
    content: str = ""
    name: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)
    tool_call_id: str | None = None


class ToolSchema(BaseModel):
    """Provider-neutral description of a callable tool."""

    name: str
    description: str
    parameters: dict[str, Any] = Field(default_factory=lambda: {"type": "object", "properties": {}})


class TokenUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def __add__(self, other: TokenUsage) -> TokenUsage:
        return TokenUsage(
            prompt_tokens=self.prompt_tokens + other.prompt_tokens,
            completion_tokens=self.completion_tokens + other.completion_tokens,
        )


class Principal(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    tenant: str
    role: Literal["viewer", "analyst", "admin"]
    key_id: str

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


class AgentSpec(BaseModel):
    """Versioned agent definition owned by a named team."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(pattern=r"^[a-z][a-z0-9-]{1,48}$")
    version: str = "1.0.0"
    display_name: str
    description: str
    owner: str = "AI Platform Engineering"
    system_prompt: str
    model: str = "fast"
    allowed_models: list[str] = Field(
        default_factory=lambda: ["fast", "balanced", "reasoning", "private", "local-grounded"]
    )
    collections: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    allowed_roles: list[Literal["viewer", "analyst", "admin"]] = Field(
        default_factory=lambda: ["analyst", "admin"]
    )
    entitlements: list[str] = Field(default_factory=lambda: ["demo"])
    max_classification: Classification = Classification.INTERNAL
    risk_level: RiskLevel = RiskLevel.LOW
    lifecycle: Lifecycle = Lifecycle.ACTIVE
    max_steps: int = Field(default=4, ge=1, le=12)
    temperature: float = Field(default=0.0, ge=0.0, le=1.0)
    citations_required: bool = True
    tags: list[str] = Field(default_factory=list)

    @field_validator("allowed_models", "collections", "tools", "entitlements")
    @classmethod
    def _unique_items(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("list values must be unique")
        return value


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input: str = Field(min_length=1, max_length=8000)
    session_id: str | None = Field(default=None, max_length=100)
    model: str | None = Field(default=None, max_length=100)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("input")
    @classmethod
    def _non_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("input must contain non-whitespace characters")
        return value.strip()


class Citation(BaseModel):
    index: int
    document_id: str
    chunk_id: str
    title: str
    collection: str
    score: float
    snippet: str


class ToolExecution(BaseModel):
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    output: Any = None
    error: str | None = None
    duration_ms: float = 0.0
    ok: bool = True
    requires_approval: bool = False


class RunResult(BaseModel):
    run_id: str
    agent: str
    agent_version: str
    status: RunStatus
    answer: str
    citations: list[Citation] = Field(default_factory=list)
    tools_used: list[ToolExecution] = Field(default_factory=list)
    usage: TokenUsage = Field(default_factory=TokenUsage)
    cost_usd: float = 0.0
    latency_ms: float = 0.0
    trace_id: str
    model: str
    cached: bool = False
    session_id: str | None = None
    approval_id: str | None = None
    warnings: list[str] = Field(default_factory=list)
    redaction_counts: dict[str, int] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=now_iso)


class Document(BaseModel):
    id: str
    collection: str
    title: str
    source: str = ""
    classification: Classification = Classification.INTERNAL
    metadata: dict[str, Any] = Field(default_factory=dict)
    content_hash: str
    created_at: str
    chunk_count: int = 0


class Chunk(BaseModel):
    id: str
    document_id: str
    collection: str
    ordinal: int
    content: str
    token_estimate: int
    metadata: dict[str, Any] = Field(default_factory=dict)


class RetrievedChunk(BaseModel):
    chunk_id: str
    document_id: str
    collection: str
    title: str
    content: str
    classification: Classification
    score: float
    vector_score: float = 0.0
    keyword_score: float = 0.0
    metadata: dict[str, Any] = Field(default_factory=dict)


class CollectionStats(BaseModel):
    collection: str
    documents: int
    chunks: int
    classifications: dict[str, int] = Field(default_factory=dict)


class IngestResult(BaseModel):
    document: Document
    duplicate: bool = False
    chunks_created: int = 0


class Approval(BaseModel):
    id: str
    tenant: str
    run_id: str
    agent: str
    tool: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    status: ApprovalStatus = ApprovalStatus.PENDING
    requested_by: str
    requested_at: str
    decided_by: str | None = None
    decided_at: str | None = None
    result: dict[str, Any] | None = None


class AuditVerification(BaseModel):
    ok: bool
    events: int
    broken_at: int | None = None
    message: str


class EvalCase(BaseModel):
    id: str
    agent: str
    input: str
    expected_keywords: list[str] = Field(default_factory=list)
    should_refuse: bool = False
    expected_citations: int = 1
    max_latency_ms: float = 2500.0
    max_cost_usd: float = 0.05
    tags: list[str] = Field(default_factory=list)


class EvalCaseResult(BaseModel):
    id: str
    agent: str
    passed: bool
    status: str
    answer: str
    latency_ms: float
    cost_usd: float
    citation_count: int
    keyword_hits: list[str] = Field(default_factory=list)
    failures: list[str] = Field(default_factory=list)
    trace_id: str = ""


class EvalReport(BaseModel):
    generated_at: str = Field(default_factory=now_iso)
    total: int
    passed: int
    failed: int
    pass_rate: float
    keyword_hit_rate: float
    citation_rate: float
    refusal_accuracy: float
    avg_latency_ms: float
    p95_latency_ms: float
    total_cost_usd: float
    cases: list[EvalCaseResult] = Field(default_factory=list)
