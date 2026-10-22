"""Composition root for the platform and its demo data."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agentforge.agents.registry import AgentRegistry, builtin_agents
from agentforge.agents.runtime import AgentRuntime
from agentforge.agents.tools import ToolRegistry, build_default_tools
from agentforge.approvals import ApprovalService
from agentforge.audit import AuditLog
from agentforge.auth import Authenticator
from agentforge.cache import TTLCache
from agentforge.config import Settings
from agentforge.cost import BudgetGuard
from agentforge.db import Database
from agentforge.evals.harness import EvalHarness
from agentforge.gateway.gateway import ModelGateway, ProviderRegistry
from agentforge.gateway.pricing import PricingCatalog
from agentforge.governance.policy import PolicyEngine
from agentforge.metrics import Metrics
from agentforge.models import Principal
from agentforge.rag.embeddings import HashingEmbedder
from agentforge.rag.ingest import KnowledgeBase
from agentforge.ratelimit import TenantRateLimiter
from agentforge.runs import RunStore
from agentforge.tracing import Tracer
from agentforge.usage import UsageStore

logger = logging.getLogger(__name__)


@dataclass
class Container:
    settings: Settings
    db: Database
    audit: AuditLog
    metrics: Metrics
    tracer: Tracer
    auth: Authenticator
    cache: TTLCache[Any]
    limiter: TenantRateLimiter
    pricing: PricingCatalog
    usage: UsageStore
    approvals: ApprovalService
    runs: RunStore
    knowledge: KnowledgeBase
    tools: ToolRegistry
    agents: AgentRegistry
    providers: ProviderRegistry
    gateway: ModelGateway
    policy: PolicyEngine
    runtime: AgentRuntime
    evals: EvalHarness
    seed_report: dict[str, Any] = field(default_factory=dict)

    def principal(self, role: str = "admin") -> Principal:
        if role == "admin":
            key = self.settings.admin_key()
        elif role == "analyst":
            key = self.settings.analyst_key()
        else:
            key = next(
                (
                    candidate
                    for candidate, config in self.settings.api_keys.items()
                    if config.role == role
                ),
                self.settings.analyst_key(),
            )
        return self.auth.authenticate(key)

    async def aclose(self) -> None:
        await self.providers.aclose()
        self.db.close()


def build_container(
    settings: Settings | None = None,
    *,
    providers: ProviderRegistry | None = None,
) -> Container:
    settings = settings or Settings.load()
    db = Database(settings.resolved_db_path())
    audit = AuditLog(db)
    metrics = Metrics()
    tracer = Tracer()
    auth = Authenticator(settings)
    cache: TTLCache[Any] = TTLCache(
        max_entries=settings.cache_max_entries,
        ttl_seconds=settings.cache_ttl_seconds,
    )
    limiter = TenantRateLimiter(
        per_minute=settings.rate_limit_per_minute,
        burst=settings.rate_limit_burst,
    )
    pricing = PricingCatalog()
    usage = UsageStore(db)
    approvals = ApprovalService(db, audit)
    runs = RunStore(db)
    knowledge = KnowledgeBase(db, HashingEmbedder())
    tools = build_default_tools(settings.resolved_data_dir(), knowledge)
    agents = AgentRegistry(builtin_agents())
    _validate_agent_tools(agents, tools)
    provider_registry = providers or ProviderRegistry.from_settings(settings)
    gateway = ModelGateway(
        settings=settings,
        providers=provider_registry,
        pricing=pricing,
        usage=usage,
        metrics=metrics,
        cache=cache,
        limiter=limiter,
        budget=BudgetGuard(usage, settings.daily_budget_usd),
    )
    policy = PolicyEngine(settings)
    runtime = AgentRuntime(
        settings=settings,
        registry=agents,
        tools=tools,
        gateway=gateway,
        knowledge=knowledge,
        policy=policy,
        approvals=approvals,
        runs=runs,
        audit=audit,
        metrics=metrics,
        tracer=tracer,
    )
    evals = EvalHarness(runtime)
    return Container(
        settings=settings,
        db=db,
        audit=audit,
        metrics=metrics,
        tracer=tracer,
        auth=auth,
        cache=cache,
        limiter=limiter,
        pricing=pricing,
        usage=usage,
        approvals=approvals,
        runs=runs,
        knowledge=knowledge,
        tools=tools,
        agents=agents,
        providers=provider_registry,
        gateway=gateway,
        policy=policy,
        runtime=runtime,
        evals=evals,
    )


def _validate_agent_tools(agents: AgentRegistry, tools: ToolRegistry) -> None:
    for agent in agents.list(include_all=True):
        missing = [name for name in agent.tools if tools.get(name) is None]
        if missing:
            raise ValueError(f"Agent '{agent.name}' references unknown tools: {missing}")


def seed_demo(container: Container, *, corpus_dir: str | Path | None = None) -> dict[str, Any]:
    """Ingest the synthetic corpus. Idempotent: duplicate documents are skipped."""
    root = Path(corpus_dir) if corpus_dir else container.settings.resolved_data_dir() / "corpus"
    if not root.exists():
        report = {"ingested": 0, "duplicates": 0, "chunks": 0, "error": "corpus_missing"}
        logger.warning("Corpus directory not found: %s", root)
        return report
    results = container.knowledge.ingest_directory(root)
    report = {
        "ingested": sum(1 for result in results if not result.duplicate),
        "duplicates": sum(1 for result in results if result.duplicate),
        "chunks": sum(result.chunks_created for result in results),
        "documents": container.knowledge.count_documents(),
        "collections": container.knowledge.collections(),
    }
    container.seed_report = report
    logger.info("Knowledge seed complete: %s", report)
    return report


def seed_if_empty(container: Container) -> dict[str, Any]:
    if container.knowledge.count_documents() == 0:
        return seed_demo(container)
    return {
        "ingested": 0,
        "duplicates": 0,
        "chunks": 0,
        "documents": container.knowledge.count_documents(),
        "collections": container.knowledge.collections(),
    }
