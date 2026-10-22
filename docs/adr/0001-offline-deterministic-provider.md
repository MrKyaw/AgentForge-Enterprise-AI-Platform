# ADR 0001: Offline deterministic provider

**Status:** Accepted  
**Date:** 2026-10-22

## Context

A reviewer should be able to run the whole platform without API keys, network access, or spend. Hosted providers also make evaluation results non-reproducible.

## Decision

Ship a `local-grounded` provider that performs extractive synthesis over retrieved sources. It is the default and the only provider available when no keys are configured. Hosted adapters exist behind the same interface.

## Consequences

- The demo is fully offline and deterministic.
- Evaluation numbers are reproducible.
- The local provider is not a language model. It cannot generalize beyond retrieved text.
- Hosted adapters are implemented and unit tested with mocked HTTP, but not integration tested against live endpoints.
- README and evaluation docs state this limitation explicitly.
