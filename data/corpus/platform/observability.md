# AI Observability Standard

> Synthetic reference document for the AgentForge demo.

## Telemetry

Every AI request emits a trace with spans for policy checks, retrieval, model calls, tool calls, and validation. Metrics include request rate, error rate, latency, token usage, cost, cache hit rate, and approval volume. Logs are structured JSON with a request identifier and tenant. Prompt and response content is minimized in logs; hashes and lengths support investigation without duplicating sensitive text.

## Service-level objectives

Client-facing assistants target 99.5% monthly availability and a p95 response time below four seconds. Batch and research workflows target completion within fifteen minutes. A breach of the error budget triggers a reliability review. Availability is measured at the gateway and at the user interface.

## Quality and drift

Offline evaluation runs on every prompt, model, or retrieval change. Online monitoring samples production interactions for groundedness, citation validity, refusal behavior, and user feedback. A drop in evaluation pass rate below the approved threshold blocks promotion. Drift checks compare retrieval coverage, query mix, and refusal rate over time.

## Incident response

An incident is declared when an AI system produces harmful output, performs an unauthorized action, leaks data, or is materially unavailable. The on-call engineer follows the runbook: contain, assess, communicate, recover, and review. High-risk agents can be disabled with a kill switch that revokes tool access and model credentials.

## Cost transparency

Cost is attributed to tenant, agent, model, and use case. Budgets have alerts at 50%, 80%, and 100% of plan. A hard budget limit blocks new model calls while allowing cached responses. Monthly FinOps reviews examine cost per successful outcome, not only cost per token.

## Dashboards and evidence

The operational dashboard shows health, latency, error rate, cost, evaluation status, and pending approvals. Audit evidence is exportable and hash-verified. Access to dashboards follows least privilege. Production readiness reviews require a dashboard link, alert routing, and a named owner.
