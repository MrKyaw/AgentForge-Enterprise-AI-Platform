"""Command-line workflows against isolated runtime state."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentforge import __version__
from agentforge.cli import build_parser, main

DATA_DIR = Path(__file__).resolve().parents[1] / "data"


@pytest.fixture()
def cli_env(monkeypatch, tmp_path: Path) -> Path:
    db_path = tmp_path / "cli.db"
    monkeypatch.setenv("AGENTFORGE_DB_PATH", str(db_path))
    monkeypatch.setenv("AGENTFORGE_DATA_DIR", str(DATA_DIR))
    monkeypatch.setenv("AGENTFORGE_SEED_ON_STARTUP", "true")
    return tmp_path


def test_parser_exposes_all_commands() -> None:
    parser = build_parser()
    commands = parser._subparsers._group_actions[0].choices  # type: ignore[attr-defined]
    assert set(commands) == {
        "serve",
        "seed",
        "ask",
        "eval",
        "doctor",
        "export-audit",
        "verify-audit",
        "demo",
    }
    parsed = parser.parse_args(["ask", "hello", "--agent", "research-copilot"])
    assert parsed.question == "hello"
    assert parsed.agent == "research-copilot"


def test_version_flag(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        build_parser().parse_args(["--version"])
    assert excinfo.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_seed_ask_doctor_and_audit_commands(
    cli_env: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["seed"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["ingested"] == 9
    assert report["chunks"] > 0
    assert len(report["collections"]) == 5

    assert main(["seed", "--force"]) == 0
    again = json.loads(capsys.readouterr().out)
    assert again["duplicates"] == 9
    assert again["ingested"] == 0

    assert main(["ask", "What is the maximum single issuer limit?", "--json"]) == 0
    run = json.loads(capsys.readouterr().out)
    assert run["status"] == "completed"
    assert run["citations"]
    assert "5%" in run["answer"]

    assert main(["ask", "What is the maximum single issuer limit?"]) == 0
    human = capsys.readouterr().out
    assert "status=completed" in human
    assert "Citations:" in human
    assert "tokens=" in human

    assert main(["verify-audit"]) == 0
    assert "OK" in capsys.readouterr().out

    assert main(["doctor", "--json"]) == 0
    checks = json.loads(capsys.readouterr().out)
    assert all(check["ok"] for check in checks)
    assert {check["check"] for check in checks} >= {"database", "knowledge", "agents"}

    assert main(["doctor"]) == 0
    assert "AgentForge" in capsys.readouterr().out

    audit_file = cli_env / "exports" / "audit.jsonl"
    assert main(["export-audit", "--output", str(audit_file)]) == 0
    assert audit_file.exists()
    assert audit_file.read_text(encoding="utf-8").strip()


def test_eval_command_writes_reports(cli_env: Path, capsys: pytest.CaptureFixture[str]) -> None:
    markdown = cli_env / "eval.md"
    json_output = cli_env / "eval.json"
    args = [
        "eval",
        "--tags",
        "refusal",
        "--output",
        str(markdown),
        "--json-output",
        str(json_output),
        "--fail-under",
        "1.0",
    ]
    assert main(args) == 0
    output = capsys.readouterr().out
    assert "pass=2/2 (100.0%)" in output
    assert markdown.exists()
    assert "# Evaluation Results" in markdown.read_text(encoding="utf-8")
    report = json.loads(json_output.read_text(encoding="utf-8"))
    assert report["total"] == 2
    assert report["pass_rate"] == 100.0

    assert main([*args, "--fail-under", "101.0"]) == 1


def test_demo_command(cli_env: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["demo"]) == 0
    output = capsys.readouterr().out
    assert "research-copilot" in output
    assert "Audit chain: verified" in output
    assert output.count("citations=") == 5
