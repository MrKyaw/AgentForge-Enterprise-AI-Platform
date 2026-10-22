"""FastAPI application factory."""

from __future__ import annotations

import logging
import re
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response

from agentforge import __version__
from agentforge.api.routes_agents import router as agents_router
from agentforge.api.routes_governance import router as governance_router
from agentforge.api.routes_knowledge import router as knowledge_router
from agentforge.api.routes_ops import router as ops_router
from agentforge.bootstrap import Container, build_container, seed_if_empty
from agentforge.config import Settings
from agentforge.errors import AgentForgeError
from agentforge.logging_config import configure_logging
from agentforge.util import new_id

logger = logging.getLogger("agentforge.api")
_request_id_pattern = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_dashboard_path = Path(__file__).with_name("dashboard.html")

TAGS_METADATA = [
    {"name": "Agents", "description": "Discover and run governed agents; inspect runs and cost."},
    {"name": "Knowledge", "description": "Ingest documents and run hybrid retrieval."},
    {"name": "Governance", "description": "Human approvals, audit evidence, and evaluations."},
    {"name": "Platform", "description": "Model catalogue, identity, and version metadata."},
]


def create_app(
    settings: Settings | None = None,
    *,
    container: Container | None = None,
    seed: bool | None = None,
) -> FastAPI:
    settings = settings or (container.settings if container else Settings.load())
    configure_logging(settings.log_level)
    container = container or build_container(settings)

    should_seed = settings.seed_on_startup if seed is None else seed
    if should_seed:
        try:
            seed_if_empty(container)
        except Exception:
            logger.exception("Demo knowledge seeding failed; continuing with empty knowledge.")

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        yield
        await container.aclose()

    app = FastAPI(
        title="AgentForge Enterprise AI Platform",
        description=(
            "A governed control plane for enterprise AI: agent runtime, hybrid RAG, "
            "model gateway, tenant budgets, human approvals, audit evidence, "
            "observability, and evaluation. Synthetic data only."
        ),
        version=__version__,
        openapi_tags=TAGS_METADATA,
        lifespan=lifespan,
        contact={
            "name": "AgentForge",
            "url": "https://github.com/MrKyaw/AgentForge-Enterprise-AI-Platform",
        },
        license_info={"name": "MIT"},
    )
    app.state.container = container
    app.state.started_at = time.monotonic()

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(settings.cors_origins),
            allow_credentials=False,
            allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
            allow_headers=["X-API-Key", "Authorization", "Content-Type", "X-Request-ID"],
            expose_headers=["X-Request-ID"],
        )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        supplied = request.headers.get("X-Request-ID", "")
        request_id = supplied if _request_id_pattern.match(supplied) else new_id("req")
        request.state.request_id = request_id
        started = time.perf_counter()
        try:
            response: Response = await call_next(request)
        except Exception:
            duration_ms = (time.perf_counter() - started) * 1000
            container.metrics.inc(
                "agentforge_http_requests_total",
                method=request.method,
                status="500",
            )
            logger.exception(
                "Unhandled request failure",
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status": 500,
                    "duration_ms": round(duration_ms, 3),
                },
            )
            raise
        duration_ms = (time.perf_counter() - started) * 1000
        response.headers["X-Request-ID"] = request_id
        container.metrics.inc(
            "agentforge_http_requests_total",
            method=request.method,
            status=str(response.status_code),
        )
        container.metrics.observe(
            "agentforge_http_request_duration_seconds",
            duration_ms / 1000,
            method=request.method,
        )
        logger.info(
            "request",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "duration_ms": round(duration_ms, 3),
            },
        )
        return response

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "img-src 'self' data:; connect-src 'self'",
        )
        return response

    @app.exception_handler(AgentForgeError)
    async def handle_agentforge_error(request: Request, exc: AgentForgeError):
        logger.warning(
            "handled error",
            extra={
                "request_id": getattr(request.state, "request_id", ""),
                "path": request.url.path,
                "status": exc.status_code,
            },
        )
        headers = dict(exc.headers)
        request_id = getattr(request.state, "request_id", None)
        if request_id:
            headers["X-Request-ID"] = request_id
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "details": exc.details,
                },
                "request_id": request_id,
            },
            headers=headers,
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(request: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "validation_error",
                    "message": "Request validation failed.",
                    "details": jsonable_encoder(exc.errors()),
                },
                "request_id": getattr(request.state, "request_id", None),
            },
        )

    @app.exception_handler(Exception)
    async def handle_unexpected(request: Request, exc: Exception):
        logger.exception(
            "unhandled exception",
            extra={
                "request_id": getattr(request.state, "request_id", ""),
                "path": request.url.path,
            },
        )
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "internal_error",
                    "message": "An unexpected error occurred.",
                    "details": {},
                },
                "request_id": getattr(request.state, "request_id", None),
            },
        )

    app.include_router(agents_router)
    app.include_router(knowledge_router)
    app.include_router(governance_router)
    app.include_router(ops_router)

    @app.get("/", include_in_schema=False)
    def dashboard() -> HTMLResponse:
        if _dashboard_path.exists():
            return HTMLResponse(_dashboard_path.read_text(encoding="utf-8"))
        return HTMLResponse(
            "<h1>AgentForge</h1><p>Dashboard asset missing. See <a href='/docs'>/docs</a>.</p>"
        )

    @app.get("/healthz", tags=["Platform"], summary="Liveness probe")
    def healthz() -> dict:
        return {
            "status": "ok",
            "service": "agentforge",
            "version": __version__,
            "environment": container.settings.environment,
        }

    @app.get("/readyz", tags=["Platform"], summary="Readiness probe")
    def readyz() -> Response:
        database_ok = container.db.ping()
        body = {
            "status": "ready" if database_ok else "not_ready",
            "checks": {
                "database": "ok" if database_ok else "failed",
                "documents": container.knowledge.count_documents(),
                "agents": len(container.agents),
                "providers": sorted(container.providers.available()),
            },
        }
        return JSONResponse(status_code=200 if database_ok else 503, content=body)

    @app.get("/metrics", include_in_schema=False)
    def prometheus_metrics() -> PlainTextResponse:
        uptime = time.monotonic() - app.state.started_at
        container.metrics.set_gauge("agentforge_uptime_seconds", round(uptime, 3))
        container.metrics.set_gauge(
            "agentforge_knowledge_documents", container.knowledge.count_documents()
        )
        container.metrics.set_gauge("agentforge_agents", len(container.agents))
        pending = sum(
            container.approvals.pending_count(tenant)
            for tenant in {config.tenant for config in container.settings.api_keys.values()}
        )
        container.metrics.set_gauge("agentforge_pending_approvals", pending)
        container.metrics.set_gauge("agentforge_info", 1, version=__version__)
        return PlainTextResponse(container.metrics.render(), media_type="text/plain; version=0.0.4")

    return app
