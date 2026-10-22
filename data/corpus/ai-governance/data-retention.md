# AI Data Retention and Privacy Standard

> Synthetic reference document for the AgentForge demo. Not legal or privacy advice.

## Prompt and response logs

AI **prompt and response logs are retained for 90 days** for quality, safety, and incident investigation. Logs must be access-controlled and linked to a trace identifier. After 90 days, logs are deleted or irreversibly aggregated unless a legal hold applies. Full prompts should not be copied into general application logs.

## Audit records

Governance decisions, approvals, model changes, and access grants are audit records and are retained for **seven years**. Audit records must be tamper-evident and available to Internal Audit and Compliance on request. Exporting audit evidence requires an approved business reason.

## Personal information

Personal information must be minimized before it enters a model prompt. Direct identifiers such as email addresses, telephone numbers, government identifiers, and payment card numbers must be redacted unless the use case explicitly requires them and has privacy approval. Sensitive personal information requires a privacy impact assessment.

## Data residency

Restricted data must remain in the approved jurisdiction. A model or platform that processes restricted data outside the approved region is not permitted, even if the vendor offers a global endpoint. Residency exceptions require approval from the Chief Privacy Officer, the Chief Information Security Officer, and the accountable executive.

## Vendor and model lifecycle

Third-party model providers must complete security, privacy, and resilience due diligence. Contracts must address data use, retention, subprocessors, incident notification, and deletion. A model that is deprecated or no longer supported must be removed from production within the agreed transition window. Decommissioning includes revoking credentials, deleting indexes, and archiving required evidence.

## Responsible AI principles

AI use must be fair, transparent, accountable, and human-centred. Teams must document intended use, known limitations, and the population affected. Evaluation must include representative cases and refusal behavior. A system must not infer sensitive traits or make decisions on prohibited grounds.

## Monitoring retention controls

The platform owner reviews retention configuration quarterly. Automated checks verify that expiry jobs are running and that legal holds are respected. A failed retention control is treated as a privacy incident.
