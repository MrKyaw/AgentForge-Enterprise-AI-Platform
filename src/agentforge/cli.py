"""Command-line interface for local demos, seeding, audits, and evaluation."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from agentforge import __version__
from agentforge.bootstrap import build_container, seed_demo, seed_if_empty
from agentforge.config import Settings
from agentforge.evals.harness import load_cases, render_markdown
from agentforge.models import Principal, RunRequest
from agentforge.util import format_usd


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agentforge",
        description="Governed enterprise AI platform: agents, RAG, gateway, audit, and evals.",
    )
    parser.add_argument("--version", action="version", version=f"AgentForge {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    serve = subparsers.add_parser("serve", help="Run the HTTP API")
    serve.add_argument("--host", default=None)
    serve.add_argument("--port", type=int, default=None)
    serve.add_argument("--reload", action="store_true", help="Enable auto-reload for development")
    serve.add_argument("--no-seed", action="store_true", help="Skip demo corpus seeding")

    seed = subparsers.add_parser("seed", help="Ingest the synthetic knowledge corpus")
    seed.add_argument("--corpus", default=None, help="Override corpus directory")
    seed.add_argument(
        "--force", action="store_true", help="Re-run ingestion even if documents exist"
    )

    ask = subparsers.add_parser("ask", help="Ask an agent from the terminal")
    ask.add_argument("question")
    ask.add_argument("--agent", default="research-copilot")
    ask.add_argument("--model", default=None)
    ask.add_argument("--role", default="admin", choices=["analyst", "admin"])
    ask.add_argument("--json", action="store_true", dest="as_json")

    evals = subparsers.add_parser("eval", help="Run the golden evaluation set")
    evals.add_argument("--output", default="docs/EVALUATION_RESULTS.md")
    evals.add_argument("--json-output", default="docs/evaluation-results.json")
    evals.add_argument("--fail-under", type=float, default=0.0)
    evals.add_argument("--tags", default="", help="Comma-separated tags to filter cases")

    doctor = subparsers.add_parser("doctor", help="Check local configuration and data")
    doctor.add_argument("--json", action="store_true", dest="as_json")

    export = subparsers.add_parser("export-audit", help="Export the audit chain as JSONL")
    export.add_argument("--output", default="var/audit.jsonl")

    subparsers.add_parser("verify-audit", help="Verify the audit chain")

    subparsers.add_parser("demo", help="Run representative questions across agents")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "serve":
        return _serve(args)
    container = build_container(Settings.load())
    try:
        if args.command == "seed":
            report = (
                seed_demo(container, corpus_dir=args.corpus)
                if args.force
                else seed_if_empty(container)
            )
            print(json.dumps(report, indent=2))
            return 0
        if args.command == "ask":
            seed_if_empty(container)
            principal = container.principal(args.role)
            return _ask(container, principal, args)
        if args.command == "eval":
            seed_if_empty(container)
            return _eval(container, args)
        if args.command == "doctor":
            return _doctor(container, as_json=args.as_json)
        if args.command == "export-audit":
            return _export_audit(container, args.output)
        if args.command == "verify-audit":
            verification = container.audit.verify()
            print(
                ("OK  " if verification.ok else "FAIL") + f" {verification.message} "
                f"({verification.events} events)"
            )
            return 0 if verification.ok else 1
        if args.command == "demo":
            seed_if_empty(container)
            return asyncio.run(_demo(container))
    finally:
        asyncio.run(container.aclose())
    return 0


def _serve(args: argparse.Namespace) -> int:
    import uvicorn

    settings = Settings.load()
    if args.no_seed:
        import os

        os.environ["AGENTFORGE_SEED_ON_STARTUP"] = "false"
    uvicorn.run(
        "agentforge.api.app:create_app",
        factory=True,
        host=args.host or settings.host,
        port=args.port or settings.port,
        reload=args.reload,
        log_config=None,
    )
    return 0


def _ask(container, principal: Principal, args: argparse.Namespace) -> int:
    run = asyncio.run(
        container.runtime.run(
            args.agent,
            RunRequest(input=args.question, model=args.model),
            principal,
        )
    )
    if args.as_json:
        print(run.model_dump_json(indent=2))
        return 0
    print(run.answer)
    print()
    print(
        f"status={run.status.value} model={run.model} "
        f"tokens={run.usage.total_tokens} cost={format_usd(run.cost_usd)} "
        f"latency={run.latency_ms:.0f}ms"
    )
    if run.citations:
        print("\nCitations:")
        for citation in run.citations:
            print(f"  [{citation.index}] {citation.title} — {citation.snippet[:140]}")
    if run.approval_id:
        print(f"\nApproval required: {run.approval_id}")
    if run.warnings:
        print(f"Warnings: {', '.join(run.warnings)}")
    return 0


def _eval(container, args: argparse.Namespace) -> int:
    path = Path(container.settings.resolved_data_dir()) / "evals" / "golden_set.jsonl"
    cases = load_cases(path)
    tags = {tag.strip() for tag in args.tags.split(",") if tag.strip()} or None
    report = asyncio.run(container.evals.run(cases, container.principal("admin"), tags=tags))
    markdown = render_markdown(report, environment=container.settings.environment)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(markdown, encoding="utf-8")
    json_output = Path(args.json_output)
    json_output.parent.mkdir(parents=True, exist_ok=True)
    json_output.write_text(report.model_dump_json(indent=2), encoding="utf-8")

    print(f"{'case':34} {'agent':26} {'status':16} result")
    print("-" * 92)
    for case in report.cases:
        print(f"{case.id:34} {case.agent:26} {case.status:16} {'PASS' if case.passed else 'FAIL'}")
    print("-" * 92)
    print(
        f"pass={report.passed}/{report.total} ({report.pass_rate:.1f}%)  "
        f"citations={report.citation_rate:.1f}%  "
        f"refusals={report.refusal_accuracy:.1f}%  "
        f"p95={report.p95_latency_ms:.0f}ms  cost=${report.total_cost_usd:.6f}"
    )
    print(f"report: {output}")
    print(f"json:   {json_output}")
    return 0 if report.pass_rate / 100.0 >= args.fail_under else 1


def _doctor(container, *, as_json: bool = False) -> int:
    checks: list[tuple[str, bool, str]] = []
    try:
        checks.append(("database", container.db.ping(), container.settings.resolved_db_path()))
    except Exception as exc:  # pragma: no cover - defensive
        checks.append(("database", False, str(exc)))
    documents = container.knowledge.count_documents()
    checks.append(("knowledge", documents > 0, f"{documents} documents"))
    checks.append(("agents", len(container.agents) > 0, f"{len(container.agents)} agents"))
    checks.append(
        (
            "providers",
            bool(container.providers.available()),
            ", ".join(sorted(container.providers.available())) or "none",
        )
    )
    golden = Path(container.settings.resolved_data_dir()) / "evals" / "golden_set.jsonl"
    checks.append(("golden set", golden.exists(), str(golden)))
    verification = container.audit.verify()
    checks.append(("audit chain", verification.ok, verification.message))
    if as_json:
        print(
            json.dumps(
                [{"check": name, "ok": ok, "detail": detail} for name, ok, detail in checks],
                indent=2,
            )
        )
    else:
        for name, ok, detail in checks:
            print(f"{'✓' if ok else '✗'} {name:12} {detail}")
        print(f"\nAgentForge {__version__} · Python {sys.version.split()[0]}")
    return 0 if all(ok for _, ok, _ in checks) else 1


def _export_audit(container, output: str) -> int:
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    count = container.audit.export_jsonl(str(path))
    print(f"Exported {count} audit events to {path}")
    return 0


async def _demo(container) -> int:
    scenarios = [
        (
            "research-copilot",
            "What is the maximum position size for a single issuer in the core equity strategy?",
        ),
        (
            "client-service-copilot",
            "How quickly must a client complaint be acknowledged?",
        ),
        (
            "governance-advisor",
            "When is a human-in-the-loop review required for an AI agent?",
        ),
        (
            "platform-architect",
            "Which storage and governance pattern should be used for governed AI data?",
        ),
        (
            "portfolio-ops-copilot",
            "What is the market value of portfolio NW-1042?",
        ),
    ]
    principal = container.principal("admin")
    for agent, question in scenarios:
        print(f"\n{'=' * 78}\n{agent} :: {question}\n{'-' * 78}")
        run = await container.runtime.run(agent, RunRequest(input=question), principal)
        print(run.answer)
        print(
            f"\n[{run.status.value}] {run.model} · {run.usage.total_tokens} tokens · "
            f"{run.latency_ms:.0f} ms · citations={len(run.citations)}"
        )
    verification = container.audit.verify()
    print(
        f"\nAudit chain: {'verified' if verification.ok else 'BROKEN'} "
        f"({verification.events} events)"
    )
    return 0 if verification.ok else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
