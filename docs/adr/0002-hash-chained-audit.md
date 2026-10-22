# ADR 0002: Hash-chained audit

**Status:** Accepted  
**Date:** 2026-10-22

## Context

Enterprise reviewers need tamper evidence for AI actions without adopting blockchain infrastructure.

## Decision

Store audit events in an append-only SQLite table where each event's hash includes the previous event's hash. Provide `verify()` and `export_jsonl()`.

## Consequences

- Tampering with any event, or deleting from the middle of the chain, is detectable.
- The chain is cheap to compute and verify.
- The chain does not prevent deletion of the database file or the tail of the chain.
- Production use requires external immutable storage and signed exports.
- The design is portable and does not introduce consensus or external services.
