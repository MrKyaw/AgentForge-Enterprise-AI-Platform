# ADR 0005: Static API keys with an explicit tenant model

**Status:** Accepted  
**Date:** 2026-10-22

## Context

The platform needs authentication and tenancy to demonstrate entitlement and isolation, but a full identity provider is out of scope for a reference implementation.

## Decision

Use static API keys configured as `key:tenant:role`. Authenticate with constant-time comparison. Provide an explicit local-development escape hatch (`AGENTFORGE_AUTH_ENABLED=false`) that is clearly labelled unsafe.

## Consequences

- Tenancy and role behaviour are demonstrable without SSO infrastructure.
- Keys are easy to rotate via configuration.
- Static keys are not suitable for production.
- The `Authenticator` class is the seam for OIDC/JWT replacement.
- Audit events reference a non-reversible key prefix, not the secret.
