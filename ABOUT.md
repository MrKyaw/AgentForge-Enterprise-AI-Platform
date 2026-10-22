# About

## What this is

AgentForge is a **reference implementation of a governed enterprise AI control plane**, built to be read, run, and tested in one sitting. It demonstrates the engineering controls that separate a working agent demo from a system an enterprise can audit, operate, and trust.

It is not a product. It is not a consultancy deliverable. It is a portfolio piece that shows how I think about AI systems in production: policy before prompts, approvals before side effects, evidence before claims, and tests before confidence.

## Who it is for

- **Recruiters and hiring managers** evaluating applied AI engineering depth.
- **Engineers** looking for a concrete pattern for governed agents.
- **Researchers and students** studying RAG, evaluation, and AI safety controls.
- **Practitioners** who want a starting point for an internal AI platform.

## A guided review path

If you have 15 minutes:

1. Read the [README](README.md) problem statement and architecture diagram.
2. Run `agentforge demo` and watch six agents produce cited, grounded answers.
3. Run `agentforge eval` and read [EVALUATION_RESULTS.md](docs/EVALUATION_RESULTS.md).
4. Run `agentforge verify-audit` and read [GOVERNANCE.md](docs/GOVERNANCE.md).
5. Skim `src/agentforge/agents/runtime.py` for the control flow.
6. Skim `tests/test_runtime.py` and `tests/test_e2e.py` for the evidence.

If you have an hour:

- Add a new agent and a golden-set case. The contribution guide shows the steps.
- Configure an OpenAI key and observe real model routing and cost accounting.
- Tamper with the database and watch `verify-audit` catch it.

## Design philosophy

- **Boring infrastructure over clever prompts.** The model is one component among many, and the least trusted.
- **Explicit boundaries.** Every extension point is named and documented. Nothing is hidden behind a TODO.
- **Determinism where it matters.** Offline provider, deterministic embeddings, fixed seeds, isolated databases.
- **Honesty about limits.** The README lists what is implemented and what is a deliberate extension point.
- **Tests as specification.** The suite is the contract for behaviour.

## Why these choices

The job descriptions that inspired this project emphasized governed AI platforms, hybrid RAG, agent orchestration, model gateways, evaluation, and responsible AI. AgentForge compresses all of those into a runnable system so a reviewer can see the trade-offs rather than read about them.

## Contact

Maintainer: **MrKyaw** — [github.com/MrKyaw](https://github.com/MrKyaw)

Issues and discussion: [github.com/MrKyaw/AgentForge-Enterprise-AI-Platform/issues](https://github.com/MrKyaw/AgentForge-Enterprise-AI-Platform/issues)
