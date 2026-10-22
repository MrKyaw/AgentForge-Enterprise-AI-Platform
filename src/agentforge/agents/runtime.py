"""Governed agent runtime: policy, retrieval, tools, synthesis, and audit."""

from __future__ import annotations

import re
from collections.abc import Sequence
from time import perf_counter

from agentforge.agents.registry import AgentRegistry
from agentforge.agents.tools import ToolContext, ToolRegistry
from agentforge.approvals import ApprovalService
from agentforge.audit import AuditLog
from agentforge.config import Settings
from agentforge.errors import AgentForgeError, PolicyViolation
from agentforge.gateway.gateway import ModelGateway
from agentforge.governance.policy import PolicyEngine
from agentforge.metrics import Metrics
from agentforge.models import (
    AgentSpec,
    Approval,
    Citation,
    Message,
    Principal,
    Role,
    RunRequest,
    RunResult,
    RunStatus,
    TokenUsage,
    ToolExecution,
)
from agentforge.rag.ingest import KnowledgeBase
from agentforge.runs import RunStore
from agentforge.security import is_refusal, redact_pii
from agentforge.tracing import Tracer
from agentforge.util import (
    canonical_json,
    clip,
    new_id,
    normalize_whitespace,
    sha256_text,
)

_CITATION = re.compile(r"\[(\d+)\]")


class AgentRuntime:
    def __init__(
        self,
        *,
        settings: Settings,
        registry: AgentRegistry,
        tools: ToolRegistry,
        gateway: ModelGateway,
        knowledge: KnowledgeBase,
        policy: PolicyEngine,
        approvals: ApprovalService,
        runs: RunStore,
        audit: AuditLog,
        metrics: Metrics,
        tracer: Tracer,
    ) -> None:
        self.settings = settings
        self.registry = registry
        self.tools = tools
        self.gateway = gateway
        self.knowledge = knowledge
        self.policy = policy
        self.approvals = approvals
        self.runs = runs
        self.audit = audit
        self.metrics = metrics
        self.tracer = tracer

    async def run(self, agent_name: str, request: RunRequest, principal: Principal) -> RunResult:
        started = perf_counter()
        agent = self.registry.get(agent_name)
        run_id = new_id("run")
        trace = self.tracer.start_trace(
            "agent.run",
            agent=agent.name,
            agent_version=agent.version,
            tenant=principal.tenant,
            run_id=run_id,
        )
        try:
            decision = self.policy.preflight(principal, agent, request.input, request.model)
            self.audit.record(
                "run.started",
                tenant=principal.tenant,
                actor=principal.key_id,
                resource=run_id,
                payload={
                    "agent": agent.name,
                    "agent_version": agent.version,
                    "model": request.model or agent.model,
                    "role": principal.role,
                    "input_sha256": sha256_text(request.input),
                    "input_chars": len(request.input),
                },
            )
            warnings = list(decision.warnings)

            with trace.span(
                "retrieval",
                collections=agent.collections,
                top_k=self.settings.retrieval_top_k,
            ) as retrieval_span:
                retrieved = self._retrieve(agent, principal, decision, request)
                retrieval_span.attributes["hits"] = len(retrieved)
            if agent.collections and not retrieved:
                warnings.append("no_retrieved_context")

            messages = [
                Message(
                    role=Role.SYSTEM,
                    content=agent.system_prompt
                    + "\n\nSOURCES:\n"
                    + self._format_sources(retrieved),
                ),
                Message(role=Role.USER, content=decision.redacted_input),
            ]
            tool_schemas = self.tools.schemas(agent.tools)
            tool_executions: list[ToolExecution] = []
            total_usage = TokenUsage()
            total_cost = 0.0
            answer = ""
            model_used = request.model or agent.model
            cached_every_call = True
            status = RunStatus.COMPLETED
            approval_id: str | None = None
            step = 0

            for step in range(agent.max_steps):
                with trace.span("model.complete", step=step, requested_model=model_used) as span:
                    gateway_result = await self.gateway.complete(
                        messages=messages,
                        model=model_used,
                        tenant=principal.tenant,
                        agent=agent.name,
                        run_id=run_id,
                        temperature=agent.temperature,
                        max_tokens=900,
                        tools=tool_schemas,
                        allowed_residencies=decision.allowed_residencies,
                    )
                    span.attributes["model"] = gateway_result.model_info.id
                    span.attributes["cached"] = gateway_result.cached
                    span.attributes["tool_calls"] = len(gateway_result.response.tool_calls)
                total_usage = total_usage + gateway_result.response.usage
                total_cost += gateway_result.cost_usd
                model_used = gateway_result.model_info.id
                cached_every_call = cached_every_call and gateway_result.cached
                if gateway_result.response.content:
                    answer = gateway_result.response.content

                calls = gateway_result.response.tool_calls
                if not calls:
                    break
                messages.append(
                    Message(
                        role=Role.ASSISTANT,
                        content=gateway_result.response.content,
                        tool_calls=calls,
                    )
                )
                paused = False
                for call in calls:
                    tool = self.tools.get(call.name)
                    if tool is None or call.name not in agent.tools:
                        self.audit.record(
                            "run.blocked",
                            tenant=principal.tenant,
                            actor=principal.key_id,
                            resource=run_id,
                            payload={"reason": "tool_not_allowed", "tool": call.name},
                        )
                        raise PolicyViolation(
                            f"Tool '{call.name}' is not permitted for agent '{agent.name}'."
                        )
                    if tool.requires_approval:
                        approval = self.approvals.request(
                            tenant=principal.tenant,
                            run_id=run_id,
                            agent=agent.name,
                            tool=call.name,
                            arguments=call.arguments,
                            requested_by=principal.key_id,
                        )
                        approval_id = approval.id
                        status = RunStatus.PENDING_APPROVAL
                        answer = (
                            f"Human approval is required before '{call.name}' can execute. "
                            f"Approval request: {approval.id}."
                        )
                        paused = True
                        break
                    with trace.span("tool.invoke", tool=call.name) as tool_span:
                        execution = self.tools.invoke(
                            call.name,
                            call.arguments,
                            self._tool_context(agent, principal, decision),
                        )
                        tool_span.attributes["ok"] = execution.ok
                        tool_span.attributes["duration_ms"] = round(execution.duration_ms, 3)
                    tool_executions.append(execution)
                    self.metrics.inc(
                        "agentforge_tool_calls_total",
                        tool=call.name,
                        status="ok" if execution.ok else "error",
                    )
                    messages.append(
                        Message(
                            role=Role.TOOL,
                            name=call.name,
                            tool_call_id=call.id,
                            content=clip(
                                canonical_json(
                                    {
                                        "ok": execution.ok,
                                        "output": execution.output,
                                        "error": execution.error,
                                    }
                                ),
                                4000,
                            ),
                        )
                    )
                if paused:
                    break
            else:
                status = RunStatus.MAX_STEPS_EXCEEDED
                warnings.append("max_steps_exceeded")
                if not answer:
                    answer = "The agent reached its tool-step limit before producing an answer."

            if status == RunStatus.COMPLETED and not answer:
                status = RunStatus.FAILED
                answer = "The model returned no answer."
                warnings.append("empty_model_response")

            citations, invalid_markers = self._citations(answer, retrieved)
            if invalid_markers:
                warnings.append("invalid_citation_markers")
            if (
                status == RunStatus.COMPLETED
                and agent.citations_required
                and not citations
                and not is_refusal(answer)
            ):
                warnings.append("answer_missing_citations")

            if self.settings.redact_output:
                output_redaction = redact_pii(answer)
                answer = output_redaction.text
                if output_redaction.total:
                    warnings.append("output_pii_redacted")
            else:
                output_redaction = None

            latency_ms = (perf_counter() - started) * 1000
            result = RunResult(
                run_id=run_id,
                agent=agent.name,
                agent_version=agent.version,
                status=status,
                answer=answer,
                citations=citations,
                tools_used=tool_executions,
                usage=total_usage,
                cost_usd=round(total_cost, 8),
                latency_ms=round(latency_ms, 3),
                trace_id=trace.id,
                model=model_used,
                cached=cached_every_call,
                session_id=request.session_id,
                approval_id=approval_id,
                warnings=_dedupe(warnings),
                redaction_counts={
                    **decision.redaction_counts,
                    **(output_redaction.counts if output_redaction else {}),
                },
                metadata={
                    "tenant": principal.tenant,
                    "role": principal.role,
                    "steps": step + 1,
                    "retrieved_chunks": len(retrieved),
                    "injection_score": decision.injection.score,
                    "model_chain_fallbacks": 0,
                },
            )
            self.runs.save(result, principal.tenant)
            trace.attributes["status"] = status.value
            trace.attributes["citations"] = len(citations)
            self.audit.record(
                "run.completed",
                tenant=principal.tenant,
                actor=principal.key_id,
                resource=run_id,
                payload={
                    "agent": agent.name,
                    "status": status.value,
                    "model": model_used,
                    "cost_usd": round(total_cost, 8),
                    "tokens": total_usage.total_tokens,
                    "citations": len(citations),
                    "tools": [execution.name for execution in tool_executions],
                    "output_sha256": sha256_text(answer),
                    "approval_id": approval_id,
                },
            )
            self.metrics.inc("agentforge_runs_total", agent=agent.name, status=status.value)
            self.metrics.observe(
                "agentforge_run_latency_seconds", latency_ms / 1000, agent=agent.name
            )
            self.metrics.inc("agentforge_citations_total", len(citations), agent=agent.name)
            return result
        except AgentForgeError as exc:
            self.audit.record(
                "run.failed",
                tenant=principal.tenant,
                actor=principal.key_id,
                resource=run_id,
                payload={"agent": agent.name, "code": exc.code, "message": exc.message},
            )
            self.metrics.inc("agentforge_runs_total", agent=agent.name, status="failed")
            trace.attributes["status"] = "failed"
            trace.attributes["error"] = exc.code
            raise
        finally:
            trace.finish()

    def _retrieve(self, agent: AgentSpec, principal: Principal, decision, request: RunRequest):
        retrieved = []
        seen: set[str] = set()
        for collection in agent.collections:
            hits = self.knowledge.search(
                request.input,
                collections=[collection],
                top_k=self.settings.retrieval_top_k,
                allowed=decision.allowed_classifications,
            )
            for hit in hits:
                if hit.chunk_id not in seen:
                    seen.add(hit.chunk_id)
                    retrieved.append(hit)
        return retrieved[:8]

    @staticmethod
    def _format_sources(retrieved: Sequence) -> str:
        if not retrieved:
            return "(no sources retrieved)"
        lines = []
        for index, hit in enumerate(retrieved, start=1):
            content = normalize_whitespace(clip(hit.content, 1000))
            lines.append(f"[{index}] {hit.title} [{hit.document_id}] :: {content}")
        return "\n".join(lines)

    def _tool_context(
        self,
        agent: AgentSpec,
        principal: Principal,
        decision,
        approval_id: str | None = None,
    ) -> ToolContext:
        return ToolContext(
            tenant=principal.tenant,
            actor=principal.key_id,
            agent=agent,
            knowledge=self.knowledge,
            allowed_classifications=decision.allowed_classifications,
            approval_id=approval_id,
            data=self.tools.data,
        )

    @staticmethod
    def _citations(answer: str, retrieved: Sequence) -> tuple[list[Citation], bool]:
        citations: list[Citation] = []
        seen: set[int] = set()
        invalid = False
        for match in _CITATION.finditer(answer):
            index = int(match.group(1))
            if index < 1 or index > len(retrieved):
                invalid = True
                continue
            if index in seen:
                continue
            seen.add(index)
            hit = retrieved[index - 1]
            citations.append(
                Citation(
                    index=index,
                    document_id=hit.document_id,
                    chunk_id=hit.chunk_id,
                    title=hit.title,
                    collection=hit.collection,
                    score=round(hit.score, 6),
                    snippet=clip(normalize_whitespace(hit.content), 320),
                )
            )
        return citations, invalid

    async def execute_approval(
        self,
        approval_id: str,
        principal: Principal,
        *,
        approve: bool,
    ) -> tuple[Approval, RunResult]:
        approval = self.approvals.get(approval_id, tenant=principal.tenant)
        run = self.runs.get(approval.run_id, tenant=principal.tenant)
        agent = self.registry.get(approval.agent)
        decision = self.policy.preflight(
            principal, agent, "Approval decision for a governed action."
        )

        if not approve:
            approval = self.approvals.decide(approval_id, principal, approve=False)
            run.status = RunStatus.REJECTED
            run.answer = (
                f"The requested action '{approval.tool}' was rejected by a human reviewer. "
                "No side effects were applied."
            )
            self.runs.save(run, principal.tenant)
            self.audit.record(
                "run.rejected",
                tenant=principal.tenant,
                actor=principal.key_id,
                resource=run.run_id,
                payload={"approval_id": approval.id, "tool": approval.tool},
            )
            self.metrics.inc("agentforge_approvals_total", decision="rejected", tool=approval.tool)
            return approval, run

        approval = self.approvals.decide(approval_id, principal, approve=True)
        execution = self.tools.invoke(
            approval.tool,
            approval.arguments,
            self._tool_context(agent, principal, decision, approval_id=approval.id),
        )
        execution.requires_approval = True
        run.tools_used.append(execution)
        run.latency_ms = round(run.latency_ms + execution.duration_ms, 3)
        if execution.ok:
            approval = self.approvals.attach_result(
                approval.id, execution.output or {}, failed=False
            )
            run.status = RunStatus.COMPLETED
            run.answer = (
                f"Approved action '{approval.tool}' executed successfully. "
                f"Result: {canonical_json(execution.output)}."
            )
        else:
            approval = self.approvals.attach_result(
                approval.id, {"error": execution.error}, failed=True
            )
            run.status = RunStatus.APPROVAL_FAILED
            run.answer = (
                f"Approved action '{approval.tool}' failed: {execution.error}. "
                "No further action was taken."
            )
        self.runs.save(run, principal.tenant)
        self.audit.record(
            "approval.executed" if execution.ok else "approval.failed",
            tenant=principal.tenant,
            actor=principal.key_id,
            resource=run.run_id,
            payload={
                "approval_id": approval.id,
                "tool": approval.tool,
                "ok": execution.ok,
            },
        )
        self.metrics.inc(
            "agentforge_approvals_total",
            decision="approved" if execution.ok else "failed",
            tool=approval.tool,
        )
        return approval, run


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))
