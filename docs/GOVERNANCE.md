# Governance

AgentForge's governance model is built on four ideas:

1. **Policy is code, not prompt text.** Entitlements, roles, classification, injection, and PII are enforced in the runtime, not suggested to the model.
2. **Side effects are gated at the tool boundary.** A prompt cannot talk its way around an approval.
3. **Every governed action leaves evidence.** Runs, approvals, and audit events are linked by IDs.
4. **Read access is filtered, not trusted.** Classification ceilings are applied by the retriever, not by the model.

## Identity and tenancy

- The caller presents one API key, which maps to `(tenant, role, key_id)` in `AGENTFORGE_API_KEYS`.
- `key_id` is a non-reversible SHA-256 prefix of the key. It identifies an actor in logs and audit without storing the secret.
- Tenants are isolated on run lists, approvals, audit reads, usage, and retrieval.
- Cross-tenant agent discovery returns `404`, not `403`, so a caller cannot enumerate another tenant's agents.

## Roles

| Role | Read | Run | Ingest/Delete | Approve/Audit/Evaluate |
|---|---|---|---|---|
| `viewer` | Public only | No | No | No |
| `analyst` | Up to confidential | Yes | No | No |
| `admin` | All | Yes | Yes | Yes |

`Authenticator.require_admin` enforces the admin boundary on the route. `PolicyEngine` enforces role boundaries at run time, including agents whose `allowed_roles` exclude a role.

## Agent entitlement

An `AgentSpec` declares:

- `entitlements`: tenants that may see and run it.
- `allowed_roles`: roles that may run it.
- `max_classification`: the highest classification its retrieval and tools may expose.
- `lifecycle`: `active` agents only. Draft, deprecated, and retired agents are blocked.
- `risk_level`: informational for reviewers; high-risk agents typically carry approval-gated tools.
- `max_steps`, `temperature`, `model`, `allowed_models`, `collections`, `tools`.

Adding a new agent requires registration in the registry and a passing unit test for its tool references (`_validate_agent_tools` runs at startup).

## Data classification

`Classification` is ordered:

`public` < `internal` < `confidential` < `restricted`

Role clearance:

| Role | Clearance |
|---|---|
| `viewer` | `public` |
| `analyst` | `public`, `internal`, `confidential` |
| `admin` | all |

An agent's `max_classification` intersects with the caller's clearance. Documents above the effective ceiling are invisible to both discovery and retrieval. The ceiling is applied in the knowledge base, so the model never sees out-of-clearance text.

## Prompt-injection handling

`assess_injection` scores input against a transparent set of signals:

- instruction override (`ignore previous instructions`)
- prompt exfiltration (`reveal system prompt`)
- jailbreak phrases (`developer mode`, `DAN mode`)
- guardrail bypass (`disable safety`)
- data exfiltration (`send api key`)
- injected instruction blocks
- role override (`act as unrestricted`)
- code blocks containing multiple `instruction` references

Each signal carries a weight. `PolicyEngine` blocks the request at or above `AGENTFORGE_INJECTION_THRESHOLD` (default 0.7) and records the score and signals in the audit payload. Lower scores produce a warning so reviewers can tune the threshold without losing visibility.

This is a fast pre-filter. It is not a complete defence and is documented as such.

## PII and secret redaction

Input redaction runs before the prompt is built. Output redaction runs before the answer is returned. Patterns:

- email
- North American phone numbers
- social insurance number (Canadian SIN)
- credit card numbers (Luhn-validated to avoid numeric-range false positives)
- IBAN
- secret-like tokens (`sk_`, `pk_`, `api_`, `key_`, `token_`)

Counts are returned in `redaction_counts` so reviewers can see what happened. Redaction does not prove absence of PII; it is one layer.

## Residency

Model aliases resolve to ordered chains. `PolicyEngine` derives `allowed_residencies`:

- default: `local`, `canada`, `global`
- restricted agents: `local`, `canada`
- `local-grounded` or `private` requests: `local` only

The gateway filters candidate models by residency before attempting a call. Hosted providers must be configured with region-appropriate endpoints; the residency value is an explicit property of `ModelInfo`, not inferred.

## Approvals

Tools declare `requires_approval=True` when they perform a side effect. The inline tool loop never executes them. Instead:

1. The run is persisted with `status=pending_approval`.
2. An approval request is created with the tool, arguments, run ID, agent, and requester.
3. The response returns `approval_id` and stops.
4. An admin can `approve` or `reject`.

On approve:

- the tool executes exactly once,
- the run is updated to `completed` or `approval_failed`,
- the approval stores the result or error,
- the action is audited.

On reject:

- no tool executes,
- the run becomes `rejected`,
- the rejection is audited.

Approvals are tenant-scoped. A second decision on an already-decided approval returns `409 conflict`.

## Audit trail

- Append-only table `audit_events` with a monotonic `seq`.
- Each event stores `prev_hash` and `hash`.
- `hash = SHA256(canonical_json(event including prev_hash))`.
- `verify()` recomputes the chain and reports the first broken sequence.
- `export_jsonl()` writes the complete chain in chronological order.
- `tamper_for_testing()` exists only to simulate an out-of-band edit in tests.

Event types emitted by the platform:

- `run.started`
- `run.completed`
- `run.failed`
- `run.blocked`
- `run.rejected`
- `knowledge.document_ingested`
- `knowledge.document_deleted`
- `approval.executed`
- `approval.failed`

Audit events do not contain raw user input, raw document content, or provider credentials. They contain hashes, identifiers, counts, and structured metadata.

### Retention and externalization

The local chain detects tampering inside the database. It does not prevent deletion of the database file or the chain tail. Production guidance:

- stream events to immutable external storage,
- sign and timestamp exports,
- define retention policy by jurisdiction,
- restrict database write access to the service account.

## Evidence linkage

Every run carries a `trace_id`. Every trace carries a `run_id`. Every approval carries a `run_id`. Every audit event for a run carries the `run_id` as `resource`. This makes a single run traceable across runtime, usage, approvals, and audit.

## Evaluation as governance

The golden set is not only a quality check; it is a regression gate. It verifies that:

- grounded answers contain required facts,
- citations are present for non-refusal answers,
- refusals occur where evidence is missing,
- latency and cost stay within configured bounds,
- run status is `completed`.

CI fails the build if the pass rate is below 100%. This prevents silent regressions in policy, retrieval, or synthesis behaviour.

## What this does not claim

- It does not provide a legally defensible compliance programme.
- It does not replace a model risk management framework.
- It does not certify that no PII can leak.
- It does not provide non-repudiation against a privileged database administrator.

It provides an auditable, testable, and readable starting point for those programmes.
