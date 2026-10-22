# Operations

## Health and readiness

| Endpoint | Purpose | Failure signal |
|---|---|---|
| `GET /healthz` | Process is alive | Connection refused or non-200 |
| `GET /readyz` | Database reachable, data loaded | `503` or `status != ready` |
| `GET /metrics` | Prometheus scrape | Stale `agentforge_uptime_seconds` |

Readiness checks database connectivity, document count, agent count, and available providers. A deployment is not ready if the database cannot be opened or seeding did not run.

## Standard startup

```bash
agentforge serve
```

On startup, with `AGENTFORGE_SEED_ON_STARTUP=true`, the server ingests the demo corpus if the database is empty. Seeding is idempotent.

For a deterministic production bootstrap, run `agentforge seed` in the deployment job and set `AGENTFORGE_SEED_ON_STARTUP=false`.

## Docker

```bash
docker compose up --build
```

The container:

- runs as non-root user `agentforge` (uid 1001),
- stores state in `/app/var` on a named volume,
- exposes port 8000,
- has a health check against `/healthz`,
- uses `uvicorn` directly (no shell).

## Backup and restore

The entire state is one SQLite file plus the data directory:

```bash
cp var/agentforge.db var/agentforge.db.backup
cp data/ var/ -r
```

Restore by stopping the process, replacing the file, and starting again. For production, move to a managed database with point-in-time recovery.

## Audit export

```bash
agentforge export-audit --output var/audit.jsonl
agentforge verify-audit
```

Export after every release and before any migration. Store exports outside the application database.

## Key operational metrics

| Metric | Type | Use |
|---|---|---|
| `agentforge_http_requests_total` | counter | Traffic and status mix |
| `agentforge_http_request_duration_seconds` | histogram | Latency SLO |
| `agentforge_runs_total` | counter | Run volume by agent and status |
| `agentforge_run_latency_seconds` | histogram | End-to-end run latency |
| `agentforge_model_requests_total` | counter | Provider traffic and errors |
| `agentforge_model_latency_seconds` | histogram | Model latency |
| `agentforge_tokens_total` | counter | Token consumption by model and kind |
| `agentforge_model_cost_usd_total` | counter | Spend by model |
| `agentforge_tool_calls_total` | counter | Tool usage and failures |
| `agentforge_approvals_total` | counter | Approval outcomes |
| `agentforge_citations_total` | counter | Citation volume |
| `agentforge_rate_limited_total` | counter | Throttling pressure |
| `agentforge_knowledge_documents` | gauge | Corpus size |
| `agentforge_agents` | gauge | Registered agents |
| `agentforge_pending_approvals` | gauge | Approval backlog |
| `agentforge_uptime_seconds` | gauge | Process uptime |

Suggested alerts:

- `rate(rate_limited_total[5m]) > 0.1 * rate(http_requests_total[5m])`
- `increase(budget_exceeded events) > 0`
- `increase(provider_error) > 0` over 15 minutes
- `agentforge_pending_approvals > 10` for 30 minutes
- readiness failures

## Runbooks

### A run returns `pending_approval`

1. List pending approvals: `GET /v1/approvals?status=pending`.
2. Inspect the tool and arguments.
3. Decide with `approve` or `reject`.
4. Verify the run status and audit event.

### Audit chain fails verification

1. Stop writes to the database.
2. Export the chain.
3. Identify `broken_at`.
4. Compare against backup and external exports.
5. Treat as a security incident if the cause is unknown.

### Provider chain exhausted

1. Check `AGENTFORGE_*` keys and endpoints.
2. Check provider status pages.
3. Confirm the platform is not unintentionally offline.
4. Review `agentforge_model_requests_total{status="error"}` for the failing provider.

### Cost overrun

1. Check `/v1/usage/summary`.
2. Lower `AGENTFORGE_DAILY_BUDGET_USD` if needed.
3. Review cache hit rate and alias policy.
4. Move low-risk tasks to `fast` or `economy`.

### Knowledge quality regression

1. Run `agentforge eval`.
2. Inspect citation counts in the report.
3. Re-run retrieval manually with `/v1/knowledge/search`.
4. Check chunking and classification filters.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `doctor` reports 0 documents | Database empty | `agentforge seed` |
| `401 authentication_required` | Missing or wrong key | Check `AGENTFORGE_API_KEYS` |
| `403 policy_violation` on run | Tenant not entitled or role blocked | Check agent entitlements and allowed roles |
| Injection false positive | Threshold too low | Raise `AGENTFORGE_INJECTION_THRESHOLD` |
| Empty answer warnings | No retrieved context | Check collections and classification ceiling |
| `502 provider_error` offline | No provider available | Configure a key or keep `local` |
| Port already in use | Another process | Change `--port` |
| Audit verify shows 0 events | Fresh database | Run `agentforge demo` |

## Logging

Structured JSON logs include request ID, method, path, status, and duration. Set `AGENTFORGE_LOG_LEVEL=DEBUG` for detailed tracing. Logs never include API keys or raw document content.

## Performance expectations

On the reference machine (Python 3.12, local provider):

- Golden set: ~3 ms per case, ~80 ms total.
- Typical governed run: 2–4 ms.
- Database size after demo: under 1 MB.
- Memory footprint: under 100 MB.

Hosted providers dominate latency and cost when configured.
