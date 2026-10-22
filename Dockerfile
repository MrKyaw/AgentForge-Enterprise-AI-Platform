# syntax=docker/dockerfile:1.7
FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip \
    && /opt/venv/bin/pip install .

FROM python:3.12-slim AS runtime

RUN groupadd --system --gid 1001 agentforge \
    && useradd --system --uid 1001 --gid agentforge --create-home agentforge
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    AGENTFORGE_ENV=production \
    AGENTFORGE_DB_PATH=/app/var/agentforge.db \
    AGENTFORGE_DATA_DIR=/app/data \
    AGENTFORGE_SEED_ON_STARTUP=true

WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY --chown=agentforge:agentforge src ./src
COPY --chown=agentforge:agentforge data ./data
RUN mkdir -p /app/var && chown -R agentforge:agentforge /app/var

USER agentforge
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2)"
CMD ["uvicorn", "agentforge.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
