# ADR 0004: SQLite for a reproducible demo

**Status:** Accepted  
**Date:** 2026-10-22

## Context

A demo that needs Postgres, Redis, and a vector database cannot be reviewed quickly and cannot be tested in CI without infrastructure.

## Decision

Use a single SQLite file with WAL mode and short transactions. Isolate all data access behind repository classes so the engine can be swapped later.

## Consequences

- One command runs the whole platform.
- Tests are fast and fully isolated.
- Single-writer concurrency is acceptable for a demo but not for high-throughput production.
- Multi-replica deployments require Postgres or a shared database.
- Row-level tenancy must be added during the migration.
