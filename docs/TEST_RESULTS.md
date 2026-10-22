# Test Results

Actual results from the reference environment. These are not projected numbers.

**Run date:** 2026-10-22  
**Platform:** macOS (darwin), Python 3.12.8  
**Command:** `python -m pytest -q --cov=agentforge --cov-report=term --junitxml=var/test-results.xml`

```text
269 passed in 8.11s

TOTAL   3080 statements   65 missed   728 branches   59 partial   96%
```

| Metric | Result |
|---|---:|
| Tests collected | 269 |
| Passed | 269 |
| Failed | 0 |
| Errors | 0 |
| Skipped | 0 |
| Statement coverage | 3080 statements, 65 missed |
| Branch coverage | 728 branches, 59 partial |
| **Total coverage** | **96%** |
| Coverage gate | 85% (passed) |
| Runtime | 8.11 s |
| Test modules | 27 |

## Environment

| Component | Version |
|---|---|
| Python | 3.12.8 |
| FastAPI | 0.139.0 |
| Pydantic | 2.12.5 |
| HTTPX | 0.28.1 |
| Uvicorn | 0.34.2 |
| pytest | 9.1.1 |
| pytest-cov | 7.1.0 |
| Ruff | 0.11.10 |

## Results by module

| Module | Tests | Focus |
|---|---:|---|
| `test_api.py` | 15 | Auth, agents, knowledge, governance, health, errors |
| `test_approvals.py` | 7 | Request, decide, duplicate, tenant isolation |
| `test_audit.py` | 6 | Append, verify, tamper detection, export |
| `test_auth.py` | 4 | Key parsing, roles, disabled auth, missing key |
| `test_bm25.py` | 4 | Tokenization, scoring, ranking |
| `test_bootstrap.py` | 7 | Composition, seeding, idempotency, tool validation |
| `test_cache.py` | 6 | TTL, eviction, hit/miss |
| `test_chunking.py` | 8 | Headings, overlap, token estimates, edge cases |
| `test_cli.py` | 5 | Seed, ask, eval, doctor, audit commands |
| `test_config.py` | 8 | Env parsing, defaults, dotenv, validation |
| `test_db.py` | 6 | Schema, transactions, row factory, concurrency |
| `test_e2e.py` | 1 | Full governed workflow including approval |
| `test_embeddings.py` | 6 | Determinism, normalization, similarity |
| `test_evals.py` | 13 | Load, filter, pass/fail, reports, refusal |
| `test_gateway.py` | 15 | Alias, fallback, retry, cache, budget, rate limit |
| `test_ingest.py` | 8 | Directory ingest, duplicate skip, delete, stats |
| `test_metrics.py` | 6 | Counters, gauges, histograms, Prometheus text |
| `test_policy.py` | 13 | Entitlement, role, lifecycle, injection, residency |
| `test_pricing.py` | 6 | Aliases, resolution, cost calculation |
| `test_providers.py` | 23 | Local provider, OpenAI/Azure/Anthropic adapters |
| `test_ratelimit.py` | 6 | Burst, refill, tenant isolation, retry-after |
| `test_registry.py` | 5 | Versions, entitlements, duplicates |
| `test_retriever.py` | 4 | Hybrid fusion, filters, classification |
| `test_runs.py` | 3 | Save, list, tenant isolation |
| `test_runtime.py` | 14 | Grounding, tools, approvals, redaction, limits |
| `test_security.py` | 16 | PII classes, Luhn, injection signals, clearance |
| `test_store.py` | 7 | Persistence, chunk queries, hashes |
| `test_tools.py` | 28 | Calculator hardening, lookups, approvals, search |
| `test_tracing.py` | 4 | Spans, attributes, nesting, serialization |
| `test_usage_cost.py` | 4 | Ledger, summaries, budget guard |
| `test_util.py` | 11 | IDs, hashing, clipping, JSON, percentages |

## Coverage by component

| Component | Coverage | Notes |
|---|---:|---|
| Agent runtime and tools | 94–98% | Error branches and unsafe calculator paths covered |
| API edge and routes | 93–97% | Middleware, validation, and error handling covered |
| Gateway and providers | 91–99% | Mocked HTTP transports for hosted adapters |
| RAG pipeline | 94–99% | Chunking, storage, retrieval, embeddings |
| Security and policy | 93–98% | PII, injection, entitlements, residency |
| Audit, approvals, runs, usage | 93–100% | Tamper path and tenant isolation covered |
| Tracing and metrics | 99% | Serialization and aggregation |

The only low-coverage module is `logging_config.py` (42%), which configures process-level logging and is exercised indirectly through the API. It contains no business logic.

## Static analysis

```text
$ ruff check src tests
All checks passed!

$ ruff format --check src tests
81 files already formatted
```

## Golden evaluation

```text
$ agentforge eval --fail-under 1.0

pass=20/20 (100.0%)  citations=100.0%  refusals=100.0%  p95=3ms  cost=$0.000000
```

| Metric | Result |
|---|---:|
| Cases | 20 |
| Passed | 20 |
| Failed | 0 |
| Pass rate | 100.0% |
| Keyword hit rate | 100.0% |
| Citation rate | 100.0% |
| Refusal accuracy | 100.0% |
| Average latency | 2.7 ms |
| p95 latency | 3.4 ms |
| Total cost | $0.000000 |

The evaluation runs on the deterministic `local-grounded` provider, so the latency and cost figures describe the control-plane path, not a hosted frontier model. See [EVALUATION_RESULTS.md](EVALUATION_RESULTS.md) for the per-case table.

## Readiness and audit checks

After seeding:

```text
$ agentforge doctor

✓ database     .../var/doctor.db
✓ knowledge    9 documents
✓ agents       6 agents
✓ providers    local
✓ golden set   .../data/evals/golden_set.jsonl
✓ audit chain  Audit chain verified.

AgentForge 1.0.0 · Python 3.12.8
```

After the demo workflow:

```text
$ agentforge verify-audit
OK  Audit chain verified. (10 events)
```

## How to reproduce

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

python -m pytest -q --cov=agentforge --cov-report=term-missing
ruff check src tests
ruff format --check src tests

AGENTFORGE_DB_PATH=var/eval.db agentforge eval --fail-under 1.0
AGENTFORGE_DB_PATH=var/demo.db agentforge demo
AGENTFORGE_DB_PATH=var/demo.db agentforge verify-audit
```

Fresh databases are used for each command so results are not affected by prior state.
