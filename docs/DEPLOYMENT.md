# Deployment

## Local development

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
agentforge serve --reload
```

`--reload` watches source files. The dashboard is served from `src/agentforge/api/dashboard.html`.

## Docker

```bash
docker compose up --build
```

Build only:

```bash
docker build -t agentforge:1.0.0 .
docker run --rm -p 8000:8000 -v agentforge-data:/app/var agentforge:1.0.0
```

The image uses a two-stage build, a non-root user, and a health check. It does not include dev dependencies.

## Configuration for deployment

Set at minimum:

```bash
AGENTFORGE_ENV=production
AGENTFORGE_AUTH_ENABLED=true
AGENTFORGE_API_KEYS=<rotated keys>
AGENTFORGE_DAILY_BUDGET_USD=<budget>
AGENTFORGE_SEED_ON_STARTUP=false
AGENTFORGE_LOG_LEVEL=INFO
```

Seed the database in the deployment job:

```bash
agentforge seed
```

## Hardened production path

1. **Identity** — replace static keys with OIDC/JWT validation and workload identity. The `Authenticator` class is the seam.
2. **Database** — move from SQLite to Postgres with row-level security and migrations. The data-access layer is isolated.
3. **Vectors** — replace hashing embeddings with a managed vector index behind the existing retriever interface.
4. **Secrets** — load provider credentials from a vault, not environment variables.
5. **Network** — put the service behind a reverse proxy with TLS, private endpoints, and egress controls.
6. **Rate limiting** — move from in-process to Redis or the API gateway for multi-replica deployments.
7. **Observability** — export OpenTelemetry spans and metrics to the enterprise backend.
8. **Audit** — stream events to immutable external storage and retain signed exports.
9. **Approvals** — add quorum, expiry, and notification integrations.
10. **Guardrails** — add a model-based injection classifier and enterprise DLP.

## Kubernetes sketch

A minimal deployment:

- Deployment with 2+ replicas
- PersistentVolumeClaim for SQLite only if single-replica; otherwise Postgres
- ConfigMap for non-secret settings
- Secret for API keys and provider credentials
- Service on port 8000
- Ingress with TLS
- Readiness probe on `/readyz`
- Liveness probe on `/healthz`
- Prometheus scrape annotation on `/metrics`

## CI/CD

The included workflow runs on every push and pull request:

1. Lint and format check
2. Tests with coverage gate (85%)
3. Golden evaluation (100% pass)
4. Package build
5. Docker build

See `.github/workflows/ci.yml`.

## Versioning and release

- Version is declared in `pyproject.toml`.
- Releases are tagged `vX.Y.Z`.
- `CHANGELOG.md` records user-visible changes.
- Database schema changes require a migration and a documented upgrade path.

## Rollback

1. Stop the service.
2. Restore the previous container image.
3. Restore the database backup taken before the release.
4. Re-run `agentforge verify-audit`.
5. Start the service.

Because audit events are chained, never restore a database that is older than the audit export without reconciling.

## Security checklist before exposing

- [ ] Rotated all demo API keys
- [ ] `AGENTFORGE_AUTH_ENABLED=true`
- [ ] TLS terminated at the edge
- [ ] Provider keys loaded from a vault
- [ ] Network egress restricted to approved endpoints
- [ ] Audit exports flowing to immutable storage
- [ ] Rate limits and budgets tuned to the tenant mix
- [ ] Dashboard not exposed to untrusted users without SSO
- [ ] Readiness and liveness probes configured
- [ ] Backup and restore tested
