# Security Policy

## Reporting a vulnerability

Please report security issues privately to the maintainer through GitHub's private vulnerability reporting on the repository. Do not open a public issue for an unpatched vulnerability.

Include:

- a description of the issue and its impact,
- reproduction steps or a proof of concept,
- affected version or commit,
- any suggested mitigation.

You can expect an acknowledgement within 72 hours and a fix or mitigation plan within 30 days for confirmed issues.

## Supported versions

Only the latest release on `main` is supported. There is no long-term support branch.

## Threat model

### In scope

- Prompt injection and instruction override.
- Data exfiltration via model output.
- Cross-tenant data access.
- Privilege escalation through role or entitlement bypass.
- Tampering with audit history.
- Unreviewed side effects.
- Cost and availability exhaustion.
- PII and secret leakage in prompts and answers.

### Out of scope

- A compromised host or database administrator.
- A compromised model provider.
- Social engineering of approvers.
- Denial of service at the network layer.
- Vulnerabilities in third-party dependencies (report upstream; we will update).

## Controls implemented

| Control | Implementation |
|---|---|
| Authentication | Constant-time API key comparison |
| Authorization | Tenant entitlements and role allow-lists |
| Data classification | Ordered levels with role and agent ceilings |
| Retrieval filtering | Ceiling applied in the knowledge base |
| Input screening | Heuristic injection scoring with configurable threshold |
| PII redaction | Input and output, with counts |
| Side-effect gating | Approval at the tool boundary |
| Audit integrity | SHA-256 hash chain with verification |
| Cost control | Per-tenant daily budget |
| Rate limiting | Per-tenant token bucket |
| Request tracing | Request IDs and structured logs |
| Secret hygiene | Keys never logged; `repr=False` on secret fields |

## Known limitations

- Static API keys are not production-grade. Replace with SSO/OIDC.
- Heuristic injection scoring is a pre-filter, not a complete defence.
- Regex PII redaction can miss novel formats and can over-redact.
- The hash chain does not prevent deletion of the whole database.
- The in-process rate limiter and cache do not span replicas.
- The local provider is extractive; it is not a security boundary for model behaviour.

## Hardening checklist

See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) for the production security checklist.
