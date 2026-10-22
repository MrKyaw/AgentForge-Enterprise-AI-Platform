# ADR 0003: Approval at the tool boundary

**Status:** Accepted  
**Date:** 2026-10-22

## Context

Prompt instructions cannot reliably prevent a model from proposing a side effect. The enforcement must be structural.

## Decision

Tools declare `requires_approval`. The runtime's inline loop never executes such a tool. It persists an approval request, returns `pending_approval`, and stops. An admin decision resumes execution exactly once.

## Consequences

- Side effects cannot occur without an explicit admin action.
- Approval, rejection, execution success, and execution failure are all audited.
- The runtime's control flow becomes slightly more complex.
- Approval state must be persisted so a restart does not lose a pending decision.
- Quorum, expiry, and notification are left as extension points.
