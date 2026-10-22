# API Guide

Base URL: `http://localhost:8000`

Interactive schema: `/docs` · OpenAPI JSON: `/openapi.json` · ReDoc: `/redoc`

## Authentication

Send the key in either header:

```http
X-API-Key: demo-analyst-key
```

```http
Authorization: Bearer demo-analyst-key
```

Keys map to a tenant and one of three roles:

| Role | Capabilities |
|---|---|
| `viewer` | Read public-classification knowledge, inspect runs and usage |
| `analyst` | Run agents, search internal/confidential knowledge |
| `admin` | Ingest/delete, approve, audit, evaluate, see all runs |

Tenant isolation is enforced on runs, approvals, audit, and usage. An entitlement check also decides which agents a tenant can see and run. Requesting an unentitled agent returns `404` on discovery and `403` on execution.

Set `AGENTFORGE_AUTH_ENABLED=false` only for local experiments. It grants an implicit `demo/admin` principal and must never be used in a shared environment.

## Conventions

- All request and response bodies are JSON.
- Unknown fields are rejected (`extra="forbid"`).
- Errors use a single envelope and always include a request ID.
- `X-Request-ID` is echoed when supplied and generated otherwise.
- List endpoints are bounded: runs `1..100`, audit `1..1000`, search `top_k 1..20`.
- Timestamps are ISO-8601 UTC strings.
- Money is USD and rounded to eight decimal places.

### Error envelope

```json
{
  "error": {
    "code": "policy_violation",
    "message": "Potential prompt injection detected; request blocked.",
    "details": {"signals": ["instruction_override"], "score": 0.65}
  },
  "request_id": "req_9f2c1a7b4e6d"
}
```

| HTTP | Code | Meaning |
|---:|---|---|
| 400 | `invalid_request` | Malformed or unknown model/alias |
| 401 | `authentication_required` | Missing or invalid key |
| 402 | `budget_exceeded` | Tenant daily budget exhausted |
| 403 | `forbidden` | Role lacks the capability |
| 403 | `policy_violation` | Entitlement, lifecycle, injection, or tool policy |
| 404 | `not_found` | Agent, run, document, or approval not visible |
| 409 | `conflict` | Invalid state transition (for example, already decided) |
| 422 | `tool_error` | Tool arguments invalid or execution failed |
| 422 | `validation_error` | Pydantic request validation |
| 429 | `rate_limited` | Tenant model-call rate exceeded; see `Retry-After` |
| 502 | `provider_error` | Every model in the fallback chain failed |
| 500 | `internal_error` | Unexpected failure; request ID is logged |

## Platform

### `GET /healthz`

Liveness. No authentication.

```json
{
  "status": "ok",
  "service": "agentforge",
  "version": "1.0.0",
  "environment": "development"
}
```

### `GET /readyz`

Dependency readiness. Returns `503` if the database cannot be reached.

```json
{
  "status": "ready",
  "checks": {
    "database": "ok",
    "documents": 9,
    "agents": 6,
    "providers": ["local"]
  }
}
```

### `GET /metrics`

Prometheus text exposition (`text/plain; version=0.0.4`). No authentication so a scraper can reach it; restrict at the network layer in production.

### `GET /v1/whoami`

```json
{
  "tenant": "demo",
  "role": "viewer",
  "key_id": "key_9b88f3b3de"
}
```

### `GET /v1/version`

```json
{"name": "AgentForge", "version": "1.0.0", "environment": "development"}
```

### `GET /v1/models`

Returns the catalogue, aliases, availability, and whether the platform is fully offline.

```json
{
  "models": [
    {
      "id": "local-grounded",
      "provider": "local",
      "display_name": "Grounded Local (offline)",
      "input_per_million": 0.0,
      "output_per_million": 0.0,
      "context_window": 32768,
      "residency": "local",
      "tier": "economy",
      "supports_tools": true,
      "available": true
    }
  ],
  "aliases": {
    "fast": ["gpt-4.1-mini", "local-grounded"],
    "balanced": ["claude-sonnet-4-5", "azure-gpt-4o", "gpt-4.1-mini", "local-grounded"]
  },
  "available_providers": ["local"],
  "offline_mode": true
}
```

## Agents

### `GET /v1/agents`

Returns the latest version of every agent the caller's tenant is entitled to. Admins see all agents.

```bash
curl -s http://localhost:8000/v1/agents \
  -H "X-API-Key: demo-analyst-key"
```

```json
[
  {
    "name": "client-service-copilot",
    "version": "1.0.0",
    "display_name": "Client Service Copilot",
    "description": "Answers service-policy questions and prepares approval-gated client service tickets using synthetic CRM data.",
    "owner": "AI Platform Engineering",
    "model": "fast",
    "collections": ["client-policy"],
    "tools": ["lookup_client", "create_service_ticket", "knowledge_search"],
    "entitlements": ["demo"],
    "max_classification": "confidential",
    "risk_level": "high",
    "lifecycle": "active",
    "max_steps": 4,
    "citations_required": true
  }
]
```

The example omits `system_prompt`, `allowed_models`, `allowed_roles`, and other fields for brevity. The live response returns the full `AgentSpec`.

### `GET /v1/agents/{name}`

Returns one agent. A tenant that is not entitled receives `404` rather than learning the agent exists.

### `GET /v1/agents/{name}/versions`

```json
["1.0.0"]
```

### `POST /v1/agents/{name}/run`

The primary endpoint. Runs policy, retrieval, tools, synthesis, citation binding, output redaction, usage accounting, and audit.

**Request**

```json
{
  "input": "What is the maximum position size for a single issuer in the core equity strategy?",
  "session_id": "review-2026-10",
  "model": null,
  "metadata": {"ticket": "OPS-441"}
}
```

| Field | Required | Rules |
|---|---|---|
| `input` | yes | 1–8000 characters, non-blank |
| `session_id` | no | ≤100 characters |
| `model` | no | Alias or model ID; must be in the agent's allow-list |
| `metadata` | no | Arbitrary JSON stored for correlation |

**Response — completed**

```json
{
  "run_id": "run_5b0e3a1c9d2f",
  "agent": "research-copilot",
  "agent_version": "1.0.0",
  "status": "completed",
  "answer": "Based on the approved knowledge base: ... A single issuer may not exceed **5% of portfolio market value** at the time of purchase [2].",
  "citations": [
    {
      "index": 2,
      "document_id": "doc_1a2b3c4d5e6f",
      "chunk_id": "chk_7a8b9c0d1e2f",
      "title": "Investment Policy Standard",
      "collection": "research",
      "score": 0.8123,
      "snippet": "Concentration limits A single issuer may not exceed 5% ..."
    }
  ],
  "tools_used": [],
  "usage": {"prompt_tokens": 812, "completion_tokens": 45},
  "cost_usd": 0.0,
  "latency_ms": 3.1,
  "trace_id": "trc_9e8d7c6b5a4f",
  "model": "local-grounded",
  "cached": false,
  "approval_id": null,
  "warnings": [],
  "redaction_counts": {},
  "metadata": {
    "tenant": "demo",
    "role": "analyst",
    "steps": 1,
    "retrieved_chunks": 6,
    "injection_score": 0.0
  }
}
```

**Response — approval required**

```json
{
  "run_id": "run_5e561dfa46af418d",
  "agent": "portfolio-ops-copilot",
  "status": "pending_approval",
  "answer": "Human approval is required before 'create_rebalance_task' can execute. Approval request: apr_7bb503193ceb46c5.",
  "approval_id": "apr_7bb503193ceb46c5",
  "citations": [],
  "warnings": []
}
```

No side effect occurs and no tool result is returned until an admin decides.

**Error — injection blocked**

```json
{
  "error": {
    "code": "policy_violation",
    "message": "Potential prompt injection detected; request blocked.",
    "details": {"signals": ["instruction_override"], "score": 0.65}
  },
  "request_id": "req_..."
}
```

### `GET /v1/runs?limit=20`

Recent runs for the caller's tenant, newest first. `limit` is `1..100`.

### `GET /v1/runs/{run_id}`

One run. Cross-tenant reads return `404`.

### `GET /v1/runs/{run_id}/trace`

Returns the span tree stored in memory for that run:

```json
{
  "id": "trc_...",
  "name": "agent.run",
  "attributes": {"agent": "research-copilot", "tenant": "demo", "status": "completed"},
  "spans": [
    {"name": "retrieval", "attributes": {"collections": ["research"], "hits": 4}, "duration_ms": 0.21},
    {"name": "model.complete", "attributes": {"model": "local-grounded", "cached": false}, "duration_ms": 1.8}
  ]
}
```

Traces are process-local. A restart clears them; run records remain.

### `GET /v1/usage/summary?days=7`

```json
{
  "tenant": "demo",
  "days": 7,
  "requests": 2,
  "cached_requests": 0,
  "total_tokens": 1606,
  "total_cost_usd": 0.0,
  "spend_today_usd": 0.0,
  "by_model": [
    {"model": "local-grounded", "requests": 2, "tokens": 1606, "cost_usd": 0.0}
  ],
  "daily": [
    {"date": "2026-10-22", "requests": 2, "tokens": 1606, "cost_usd": 0.0}
  ]
}
```

`days` is `1..90`.

## Knowledge

### `GET /v1/knowledge/collections`

```json
[
  {
    "collection": "research",
    "documents": 2,
    "chunks": 13,
    "classifications": {"internal": 2}
  }
]
```

### `GET /v1/knowledge/documents?collection=research`

Lists documents at or below the caller's clearance. `viewer` sees only `public`; `analyst` sees up to `confidential`; `admin` sees all.

### `POST /v1/knowledge/documents` — admin

```json
{
  "collection": "platform",
  "title": "Incident Response Addendum",
  "content": "# Incident Response\n\n...",
  "source": "synthetic://platform/incident-addendum",
  "classification": "internal",
  "metadata": {"owner": "platform-team"}
}
```

Returns `201`:

```json
{
  "document": {
    "id": "doc_...",
    "collection": "platform",
    "title": "Incident Response Addendum",
    "classification": "internal",
    "content_hash": "...",
    "chunk_count": 4
  },
  "duplicate": false,
  "chunks_created": 4
}
```

Re-ingesting identical content into the same collection returns `duplicate: true` and creates no chunks. This makes seeding and retries safe.

Audit event: `knowledge.document_ingested` (with collection, classification, chunk count, and content hash). Raw content is not written to the audit payload.

### `DELETE /v1/knowledge/documents/{id}` — admin

```json
{"deleted": true, "id": "doc_..."}
```

Audit event: `knowledge.document_deleted`.

### `POST /v1/knowledge/search`

```json
{
  "query": "human-in-the-loop requirements",
  "collections": ["ai-governance"],
  "top_k": 4,
  "filters": {"owner": "risk"}
}
```

Returns `RetrievedChunk` objects ordered by fused score:

```json
[
  {
    "chunk_id": "chk_...",
    "document_id": "doc_...",
    "collection": "ai-governance",
    "title": "Model Risk Standard",
    "content": "Human-in-the-loop A human-in-the-loop review is required ...",
    "classification": "internal",
    "score": 0.8341,
    "vector_score": 0.721,
    "keyword_score": 0.912,
    "metadata": {}
  }
]
```

`filters` are exact-match equality filters over document metadata.

## Governance

### `GET /v1/approvals?status=pending`

```json
[
  {
    "id": "apr_7bb503193ceb46c5",
    "tenant": "demo",
    "run_id": "run_5e561dfa46af418d",
    "agent": "portfolio-ops-copilot",
    "tool": "create_rebalance_task",
    "arguments": {"portfolio_id": "NW-1042", "reason": "Raise cash to 10%"},
    "status": "pending",
    "requested_by": "key_...",
    "requested_at": "2026-10-22T11:59:44.163Z",
    "decided_by": null,
    "decided_at": null,
    "result": null
  }
]
```

### `POST /v1/approvals/{id}/approve` — admin

Executes the tool exactly once and resumes the run.

```json
{
  "approval": {
    "id": "apr_...",
    "status": "approved",
    "decided_by": "key_...",
    "result": {"task_id": "task_...", "status": "created"}
  },
  "run": {
    "run_id": "run_...",
    "status": "completed",
    "answer": "Approved action 'create_rebalance_task' executed successfully. Result: {...}."
  }
}
```

If the tool fails, the approval becomes `failed` and the run becomes `approval_failed`. The failure is audited.

### `POST /v1/approvals/{id}/reject` — admin

```json
{
  "approval": {"id": "apr_...", "status": "rejected"},
  "run": {
    "status": "rejected",
    "answer": "The requested action 'create_rebalance_task' was rejected by a human reviewer. No side effects were applied."
  }
}
```

### `GET /v1/audit?limit=100&event_type=run.completed` — admin

Returns newest first. `limit` is `1..1000`.

```json
[
  {
    "seq": 12,
    "event_id": "evt_...",
    "ts": "2026-10-22T11:59:44.201Z",
    "event_type": "run.completed",
    "tenant": "demo",
    "actor": "key_...",
    "resource": "run_...",
    "payload": {
      "agent": "portfolio-ops-copilot",
      "status": "pending_approval",
      "model": "local-grounded",
      "cost_usd": 0.0,
      "tokens": 731,
      "citations": 0,
      "tools": ["portfolio_lookup"],
      "output_sha256": "...",
      "approval_id": "apr_..."
    },
    "prev_hash": "...",
    "hash": "..."
  }
]
```

### `GET /v1/audit/verify` — admin

```json
{"ok": true, "events": 10, "broken_at": null, "message": "Audit chain verified."}
```

A broken chain returns `ok: false`, `broken_at`, and a failure message. Verification is read-only.

### `POST /v1/evals/run` — admin

```json
{"tags": ["refusal"]}
```

Omit tags to run the full golden set. Returns the `EvalReport` and writes nothing to disk (the CLI writes Markdown/JSON).

```json
{
  "generated_at": "2026-10-22T11:58:12.849Z",
  "total": 20,
  "passed": 20,
  "failed": 0,
  "pass_rate": 100.0,
  "keyword_hit_rate": 100.0,
  "citation_rate": 100.0,
  "refusal_accuracy": 100.0,
  "avg_latency_ms": 2.706,
  "p95_latency_ms": 3.351,
  "total_cost_usd": 0.0,
  "cases": []
}
```

The `cases` array is populated in the live response.

## Dashboard

`GET /` serves a self-contained HTML dashboard with four workspaces:

- **Ask an agent** — select an agent, run a question, inspect citations and tool calls.
- **Knowledge** — hybrid search and collection statistics.
- **Governance** — approval queue and audit-chain verification.
- **Usage & runs** — spend, token totals, model mix, and recent runs.

The dashboard uses browser storage for the demo keys. It is a review aid, not a production console.

## HTTP status summary

| Status | Used for |
|---:|---|
| 200 | Successful reads and runs |
| 201 | Document ingestion |
| 400 | Invalid model or alias |
| 401 | Authentication failure |
| 402 | Budget exhausted |
| 403 | Role or policy denial |
| 404 | Hidden or missing resource |
| 409 | Approval already decided |
| 422 | Validation or tool failure |
| 429 | Rate limit |
| 500 | Unexpected error |
| 502 | Provider chain failure |
| 503 | Readiness failure |
