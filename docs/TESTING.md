# Testing

## Strategy

The suite is built around three principles:

1. **Every governed path is tested directly.** Policy, retrieval, tools, gateway, approvals, audit, and evaluation each have their own module tests.
2. **Isolation is non-negotiable.** Each test gets a fresh SQLite database and a deterministic environment via `conftest.py` fixtures.
3. **No external dependencies.** Hosted providers are tested with mocked HTTP transports. No network, no keys, no spend.

## Fixtures

`tests/conftest.py` provides:

- `settings` — a complete `Settings` instance with a temporary database path and data directory.
- `container` — a wired `Container` built from those settings.
- `seeded` — the container after ingesting the demo corpus.
- `principal` — an admin principal for the demo tenant.
- `auth_headers` — headers for the admin key.
- `cli_env` — a temporary working directory with corpus and eval data copied in.

Tests use plain `asyncio.run` rather than `pytest-asyncio`, keeping dependencies minimal.

## Coverage policy

- Gate: 85% (actual: 96% branch coverage).
- Report: `docs/TEST_RESULTS.md`.
- `logging_config.py` is the only module below the gate at 42%. It configures process logging and contains no business logic.

## Test inventory

| Module | Focus |
|---|---|
| `test_api.py` | HTTP edge, auth, routes, errors, dashboard |
| `test_approvals.py` | Approval lifecycle and tenant isolation |
| `test_audit.py` | Append, verify, tamper, export |
| `test_auth.py` | Key parsing, roles, disabled auth |
| `test_bm25.py` | Tokenization and scoring |
| `test_bootstrap.py` | Composition and seeding |
| `test_cache.py` | TTL and eviction |
| `test_chunking.py` | Boundaries and overlap |
| `test_cli.py` | Command surface |
| `test_config.py` | Env parsing and validation |
| `test_db.py` | Schema and transactions |
| `test_e2e.py` | Full governed workflow |
| `test_embeddings.py` | Determinism and similarity |
| `test_evals.py` | Harness behaviour |
| `test_gateway.py` | Routing, fallback, cache, budget, limits |
| `test_ingest.py` | Ingestion and deduplication |
| `test_metrics.py` | Registry and Prometheus text |
| `test_policy.py` | Authorization and guardrails |
| `test_pricing.py` | Aliases and cost |
| `test_providers.py` | All four adapters with mocked HTTP |
| `test_ratelimit.py` | Token bucket |
| `test_registry.py` | Agent versions and entitlements |
| `test_retriever.py` | Hybrid fusion and filters |
| `test_runs.py` | Persistence and scoping |
| `test_runtime.py` | End-to-end governed runs |
| `test_security.py` | PII, injection, clearance |
| `test_store.py` | Document and chunk queries |
| `test_tools.py` | Calculator hardening and tool behaviour |
| `test_tracing.py` | Span tree |
| `test_usage_cost.py` | Ledger and budget |
| `test_util.py` | Utilities |

## Running

```bash
python -m pytest -q
python -m pytest --cov=agentforge --cov-report=term-missing --cov-fail-under=85
python -m pytest tests/test_runtime.py -q
python -m pytest -k "injection or approval" -q
```

## Adding tests

- Put unit tests next to the module they cover.
- Use the `seeded` fixture when retrieval is needed.
- Use `asyncio.run` for async code.
- Never hit the network. Mock HTTP transports.
- Assert on stable identifiers and counts, not on exact floating-point scores.
- Keep tests deterministic: no `time.sleep`, no randomness, no shared state.

## CI

`.github/workflows/ci.yml` runs lint, tests, coverage, golden evaluation, package build, and Docker build on Python 3.11 and 3.12. A failing gate blocks merge.
