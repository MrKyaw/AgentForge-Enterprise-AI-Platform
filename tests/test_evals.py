"""Golden evaluation harness: scoring, filtering, and reporting."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from agentforge.bootstrap import Container
from agentforge.evals.harness import EvalHarness, load_cases, render_markdown
from agentforge.models import EvalCase, EvalReport

DATA_DIR = Path(__file__).resolve().parents[1] / "data"


def _report(container: Container, cases: list[EvalCase], tags: set[str] | None = None):
    return asyncio.run(container.evals.run(cases, container.principal("admin"), tags=tags))


def test_golden_set_loads() -> None:
    cases = load_cases(DATA_DIR / "evals" / "golden_set.jsonl")
    assert len(cases) == 20
    assert len({case.id for case in cases}) == 20
    assert sum(case.should_refuse for case in cases) == 2
    assert all(case.agent for case in cases)


def test_loader_reports_bad_lines(tmp_path: Path) -> None:
    path = tmp_path / "bad.jsonl"
    path.write_text("{not json}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="line 1"):
        load_cases(path)


def test_loader_skips_blank_and_comment_lines(tmp_path: Path) -> None:
    path = tmp_path / "cases.jsonl"
    path.write_text(
        "\n# comment\n"
        + json.dumps(
            {
                "id": "one",
                "agent": "research-copilot",
                "input": "q",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    cases = load_cases(path)
    assert [case.id for case in cases] == ["one"]


def test_refusal_tags_pass(seeded: Container) -> None:
    cases = load_cases(DATA_DIR / "evals" / "golden_set.jsonl")
    report = _report(seeded, cases, tags={"refusal"})
    assert report.total == 2
    assert report.failed == 0
    assert report.pass_rate == 100.0
    assert report.refusal_accuracy == 100.0


def test_grounding_tags_pass(seeded: Container) -> None:
    cases = load_cases(DATA_DIR / "evals" / "golden_set.jsonl")
    report = _report(seeded, cases, tags={"grounding"})
    assert report.total >= 1
    assert report.pass_rate == 100.0
    assert report.keyword_hit_rate == 100.0
    assert report.citation_rate == 100.0


def test_failed_case_records_specific_failures(seeded: Container) -> None:
    case = EvalCase(
        id="forced-failure",
        agent="research-copilot",
        input="What is the maximum position size for a single issuer?",
        expected_keywords=["nonexistent-keyword"],
        expected_citations=5,
        max_latency_ms=0.0,
        max_cost_usd=-1.0,
    )
    report = _report(seeded, [case])
    assert report.total == 1
    assert report.passed == 0
    assert report.pass_rate == 0.0
    failure_text = " ".join(report.cases[0].failures)
    assert "missing_keyword:nonexistent-keyword" in failure_text
    assert "insufficient_citations" in failure_text
    assert "latency:" in failure_text
    assert "cost:" in failure_text


def test_expected_refusal_mismatch(seeded: Container) -> None:
    case = EvalCase(
        id="wrong-refusal",
        agent="research-copilot",
        input="What is the maximum position size for a single issuer?",
        should_refuse=True,
    )
    report = _report(seeded, [case])
    assert report.passed == 0
    assert "expected_refusal" in report.cases[0].failures
    assert report.refusal_accuracy == 0.0


def test_unexpected_refusal(seeded: Container) -> None:
    case = EvalCase(
        id="unexpected-refusal",
        agent="research-copilot",
        input="What was the portfolio return in 2019?",
        expected_citations=1,
    )
    report = _report(seeded, [case])
    assert report.passed == 0
    assert "unexpected_refusal" in report.cases[0].failures


def test_runtime_errors_are_captured(seeded: Container) -> None:
    case = EvalCase(id="missing-agent", agent="does-not-exist", input="Hello")
    report = _report(seeded, [case])
    assert report.passed == 0
    assert report.cases[0].status == "error"
    assert report.cases[0].failures == ["runtime_error:not_found"]


def test_harness_reports_are_serializable(seeded: Container) -> None:
    cases = load_cases(DATA_DIR / "evals" / "golden_set.jsonl")[:2]
    report = _report(seeded, cases)
    assert isinstance(report, EvalReport)
    restored = EvalReport.model_validate_json(report.model_dump_json())
    assert restored.total == len(cases)
    assert report.p95_latency_ms >= 0


def test_markdown_report_contains_summary_and_cases(seeded: Container) -> None:
    cases = load_cases(DATA_DIR / "evals" / "golden_set.jsonl")[:2]
    report = _report(seeded, cases)
    markdown = render_markdown(report, environment="test")
    assert "# Evaluation Results" in markdown
    assert "Environment: `test`" in markdown
    assert "| Pass rate |" in markdown
    assert f"`{cases[0].id}`" in markdown
    assert "local-grounded" in markdown


def test_empty_selection_produces_zeroed_report(seeded: Container) -> None:
    report = _report(seeded, load_cases(DATA_DIR / "evals" / "golden_set.jsonl"), tags={"none"})
    assert report.total == 0
    assert report.pass_rate == 0.0
    assert report.refusal_accuracy == 100.0
    assert report.avg_latency_ms == 0.0
    assert report.p95_latency_ms == 0.0


def test_harness_accepts_explicit_runtime(seeded: Container) -> None:
    assert isinstance(EvalHarness(seeded.runtime), EvalHarness)
