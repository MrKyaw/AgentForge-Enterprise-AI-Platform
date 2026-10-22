# AI Model Risk Standard

> Synthetic reference document for the AgentForge demo. Not legal or regulatory advice.

## Scope

This standard applies to every AI system that supports, informs, or automates a business process at Lumen Ridge, including generative AI assistants, agents, retrieval systems, and classical machine-learning models. Each system is registered in the AI inventory with an accountable owner, business purpose, model tier, data classification, and review date.

## Risk tiering

AI use cases are classified as low, medium, or high risk. **High-risk** use cases include client-facing advice, trading or portfolio decisions, credit or suitability decisions, fraud detection with client impact, and any process that can materially affect a client outcome. High-risk systems require a model risk review before production, independent validation, ongoing monitoring, and a documented fallback plan.

## Human-in-the-loop

A **human-in-the-loop** review is required for every high-risk AI action before it takes effect. The reviewer must have the authority, context, and time to challenge the recommendation. A click-through acknowledgement without evidence review is not sufficient. Low-risk informational assistants may operate without per-action review but remain subject to monitoring and spot checks.

## Approval and accountability

The **AI Review Board** approves high-risk use cases and material changes. The board includes representatives from business, technology, risk, compliance, legal, privacy, and information security. The accountable executive remains responsible for the system even when the board has approved it. AI cannot be used to make a final investment decision without a qualified human decision-maker.

## Controls

Every agent must be registered, versioned, and assigned to a tenant with least-privilege entitlements. Production access requires an approved use case, a completed risk assessment, and evidence of evaluation. Agents must have a documented owner, a decommissioning plan, and a kill switch. Tool access must be scoped to the task, and high-impact tools require approval.

## Prompt injection and data protection

Retrieved content is untrusted data, not instruction. Systems must separate instructions from retrieved text, apply input and output controls, and log injection signals. Secrets must never appear in prompts. Personal information must be minimized, redacted where appropriate, and protected by role-based access.

## Monitoring and incidents

Production systems monitor quality, drift, latency, cost, and safety signals. An AI incident includes harmful output, unauthorized action, data leakage, material model drift, or extended unavailability. Incidents are logged, triaged, and reported through the operational risk process. A high-severity incident triggers suspension of the affected use case until the AI Review Board approves remediation.

## Change management

Prompts, models, indexes, tools, and agent policies are controlled assets. Material changes require evaluation evidence, peer review, and approval. Emergency changes require retrospective review within five business days. Every production version must be reproducible from source control.
