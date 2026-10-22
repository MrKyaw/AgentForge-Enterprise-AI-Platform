"""Reproducible evaluation of grounded answers, citations, refusal, latency, and cost."""

from __future__ import annotations

import math
from pathlib import Path
from time import perf_counter

from agentforge.agents.runtime import AgentRuntime
from agentforge.errors import AgentForgeError
from agentforge.models import (
    EvalCase,
    EvalCaseResult,
    EvalReport,
    Principal,
    RunRequest,
    RunStatus,
)
from agentforge.security import is_refusal
from agentforge.util import now_iso, percent


def load_cases(path: str | Path) -> list[EvalCase]:
    file_path = Path(path)
    cases: list[EvalCase] = []
    with file_path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                cases.append(EvalCase.model_validate_json(line))
            except ValueError as exc:
                raise ValueError(f"Invalid eval case on line {line_number}: {exc}") from exc
    return cases


class EvalHarness:
    def __init__(self, runtime: AgentRuntime) -> None:
        self.runtime = runtime

    async def run(
        self,
        cases: list[EvalCase],
        principal: Principal,
        *,
        tags: set[str] | None = None,
    ) -> EvalReport:
        selected = [case for case in cases if not tags or tags & set(case.tags)]
        results: list[EvalCaseResult] = []
        for case in selected:
            results.append(await self._run_case(case, principal))
        total = len(results)
        passed = sum(1 for result in results if result.passed)
        failures = total - passed
        non_refusal = [case for case in selected if not case.should_refuse]
        keyword_cases = [case for case in non_refusal if case.expected_keywords]
        keyword_pass = sum(
            1
            for case in keyword_cases
            if all(
                keyword.lower() in _result_for(results, case.id).answer.lower()
                for keyword in case.expected_keywords
            )
        )
        citation_cases = [case for case in non_refusal if case.expected_citations > 0]
        citation_pass = sum(
            1
            for case in citation_cases
            if _result_for(results, case.id).citation_count >= case.expected_citations
        )
        refusal_cases = [case for case in selected if case.should_refuse]
        refusal_pass = sum(
            1 for case in refusal_cases if is_refusal(_result_for(results, case.id).answer)
        )
        latencies = sorted(result.latency_ms for result in results)
        p95 = (
            latencies[min(len(latencies) - 1, math.ceil(len(latencies) * 0.95) - 1)]
            if latencies
            else 0.0
        )
        return EvalReport(
            generated_at=now_iso(),
            total=total,
            passed=passed,
            failed=failures,
            pass_rate=percent(passed, total),
            keyword_hit_rate=percent(keyword_pass, len(keyword_cases)),
            citation_rate=percent(citation_pass, len(citation_cases)),
            refusal_accuracy=percent(refusal_pass, len(refusal_cases)) if refusal_cases else 100.0,
            avg_latency_ms=round(sum(latencies) / len(latencies), 3) if latencies else 0.0,
            p95_latency_ms=round(p95, 3),
            total_cost_usd=round(sum(result.cost_usd for result in results), 8),
            cases=results,
        )

    async def _run_case(self, case: EvalCase, principal: Principal) -> EvalCaseResult:
        started = perf_counter()
        try:
            run = await self.runtime.run(
                case.agent,
                RunRequest(input=case.input, metadata={"eval_case": case.id}),
                principal,
            )
        except AgentForgeError as exc:
            return EvalCaseResult(
                id=case.id,
                agent=case.agent,
                passed=False,
                status="error",
                answer=f"{exc.code}: {exc.message}",
                latency_ms=round((perf_counter() - started) * 1000, 3),
                cost_usd=0.0,
                citation_count=0,
                failures=[f"runtime_error:{exc.code}"],
            )
        failures: list[str] = []
        lowered = run.answer.lower()
        keyword_hits = [keyword for keyword in case.expected_keywords if keyword.lower() in lowered]
        if case.should_refuse:
            if not is_refusal(run.answer):
                failures.append("expected_refusal")
        else:
            if is_refusal(run.answer):
                failures.append("unexpected_refusal")
            for keyword in case.expected_keywords:
                if keyword not in keyword_hits:
                    failures.append(f"missing_keyword:{keyword}")
            if len(run.citations) < case.expected_citations:
                failures.append(
                    f"insufficient_citations:{len(run.citations)}<{case.expected_citations}"
                )
        if run.status != RunStatus.COMPLETED:
            failures.append(f"status:{run.status.value}")
        if run.latency_ms > case.max_latency_ms:
            failures.append(f"latency:{run.latency_ms:.0f}>{case.max_latency_ms:.0f}")
        if run.cost_usd > case.max_cost_usd:
            failures.append(f"cost:{run.cost_usd}> {case.max_cost_usd}")
        return EvalCaseResult(
            id=case.id,
            agent=case.agent,
            passed=not failures,
            status=run.status.value,
            answer=run.answer,
            latency_ms=run.latency_ms,
            cost_usd=run.cost_usd,
            citation_count=len(run.citations),
            keyword_hits=keyword_hits,
            failures=failures,
            trace_id=run.trace_id,
        )


def _result_for(results: list[EvalCaseResult], case_id: str) -> EvalCaseResult:
    return next(result for result in results if result.id == case_id)


def render_markdown(report: EvalReport, *, environment: str = "local") -> str:
    """Render a human-readable report suitable for a README or CI artifact."""
    lines = [
        "# Evaluation Results",
        "",
        f"Generated: `{report.generated_at}` · Environment: `{environment}`",
        "",
        "## Summary",
        "",
        "| Metric | Result |",
        "|---|---:|",
        f"| Cases | {report.total} |",
        f"| Passed | {report.passed} |",
        f"| Failed | {report.failed} |",
        f"| Pass rate | **{report.pass_rate:.1f}%** |",
        f"| Keyword hit rate | {report.keyword_hit_rate:.1f}% |",
        f"| Citation rate | {report.citation_rate:.1f}% |",
        f"| Refusal accuracy | {report.refusal_accuracy:.1f}% |",
        f"| Average latency | {report.avg_latency_ms:.1f} ms |",
        f"| p95 latency | {report.p95_latency_ms:.1f} ms |",
        f"| Total model cost | ${report.total_cost_usd:.6f} |",
        "",
        "## Cases",
        "",
        "| Case | Agent | Status | Pass | Citations | Latency | Failures |",
        "|---|---|---|---:|---:|---:|---|",
    ]
    for case in report.cases:
        failures = ", ".join(case.failures) if case.failures else "—"
        lines.append(
            f"| `{case.id}` | `{case.agent}` | {case.status} | "
            f"{'✅' if case.passed else '❌'} | {case.citation_count} | "
            f"{case.latency_ms:.0f} ms | {failures} |"
        )
    lines.extend(
        [
            "",
            "> The offline `local-grounded` provider is deterministic and extractive, so "
            "latency and cost figures reflect the control-plane path rather than a hosted "
            "frontier model. Configure a provider key to exercise hosted models.",
            "",
        ]
    )
    return "\n".join(lines)
