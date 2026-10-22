# Changelog

All notable changes to this project are documented here. The format follows Keep a Changelog and the project uses semantic versioning.

## [1.0.0] — 2026-10-22

### Added

- Governed agent runtime with policy pre-flight, hybrid retrieval, tool loop, approvals, citations, and audit.
- Six reference agents: research, client service, governance, platform, distribution, portfolio operations.
- Hybrid RAG: heading-aware chunking, hashing embeddings, BM25, fused scoring, classification filters.
- Model gateway with aliases, fallback, retry, residency, caching, rate limiting, and budgets.
- Provider adapters: local grounded, OpenAI, Azure OpenAI, Anthropic.
- Human approval pause/resume with rejection and failure paths.
- Append-only SHA-256 hash-chained audit log with verification and JSONL export.
- PII redaction and heuristic prompt-injection scoring.
- Request tracing, Prometheus metrics, health and readiness probes.
- Token and cost ledger with per-tenant usage summaries.
- Golden evaluation set (20 cases) with Markdown and JSON reports.
- Self-contained operator dashboard.
- CLI: serve, seed, ask, eval, doctor, export-audit, verify-audit, demo.
- Dockerfile and docker-compose.
- Comprehensive documentation: architecture, API, governance, evaluation, operations, deployment, testing, ADRs.
- 269 tests with 96% branch coverage.

### Changed

- None (initial release).

### Fixed

- `auth.py`: auth-disabled path now executes before the missing-key check.
- `cost.py`: budget check returns non-negative remaining budget.
- `tools.py`: calculator strips thousands separators safely; power operator guard checks the correct node; async tool coroutines are closed before raising.
- `dashboard.html`: corrected an invalid CSS declaration.

## [Unreleased]

### Planned

- OIDC/SSO identity provider integration.
- Postgres and managed vector index backends.
- OpenTelemetry export.
- Expanded evaluation slices.
