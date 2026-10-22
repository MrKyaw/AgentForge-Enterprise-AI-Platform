"""Agent discovery, execution, runs, and usage endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from agentforge.api.deps import get_container, get_principal
from agentforge.bootstrap import Container
from agentforge.errors import NotFoundError
from agentforge.models import AgentSpec, Principal, RunRequest, RunResult

router = APIRouter(prefix="/v1", tags=["Agents"])


@router.get("/agents", response_model=list[AgentSpec], summary="List available agents")
def list_agents(
    principal: Principal = Depends(get_principal),
    container: Container = Depends(get_container),
) -> list[AgentSpec]:
    return container.agents.list(tenant=principal.tenant, include_all=principal.is_admin)


@router.get("/agents/{agent_name}", response_model=AgentSpec, summary="Get an agent definition")
def get_agent(
    agent_name: str,
    principal: Principal = Depends(get_principal),
    container: Container = Depends(get_container),
) -> AgentSpec:
    agent = container.agents.get(agent_name)
    if principal.tenant not in agent.entitlements and not principal.is_admin:
        raise NotFoundError(f"Agent not found: {agent_name}")
    return agent


@router.get(
    "/agents/{agent_name}/versions",
    response_model=list[str],
    summary="List registered versions",
)
def list_agent_versions(
    agent_name: str,
    _principal: Principal = Depends(get_principal),
    container: Container = Depends(get_container),
) -> list[str]:
    return container.agents.versions(agent_name)


@router.post(
    "/agents/{agent_name}/run",
    response_model=RunResult,
    summary="Run an agent through policy, retrieval, tools, and synthesis",
)
async def run_agent(
    agent_name: str,
    body: RunRequest,
    principal: Principal = Depends(get_principal),
    container: Container = Depends(get_container),
) -> RunResult:
    return await container.runtime.run(agent_name, body, principal)


@router.get("/runs", response_model=list[RunResult], summary="List recent runs for the tenant")
def list_runs(
    limit: int = Query(default=20, ge=1, le=100),
    principal: Principal = Depends(get_principal),
    container: Container = Depends(get_container),
) -> list[RunResult]:
    return container.runs.list(principal.tenant, limit=limit)


@router.get("/runs/{run_id}", response_model=RunResult, summary="Get a run result")
def get_run(
    run_id: str,
    principal: Principal = Depends(get_principal),
    container: Container = Depends(get_container),
) -> RunResult:
    return container.runs.get(run_id, tenant=principal.tenant)


@router.get("/runs/{run_id}/trace", summary="Get trace spans for a run")
def get_run_trace(
    run_id: str,
    principal: Principal = Depends(get_principal),
    container: Container = Depends(get_container),
) -> dict:
    run = container.runs.get(run_id, tenant=principal.tenant)
    trace = container.tracer.get(run.trace_id)
    if trace is None:
        raise NotFoundError(f"Trace not found for run: {run_id}")
    return trace.to_dict()


@router.get("/usage/summary", summary="AI consumption and cost summary")
def usage_summary(
    days: int = Query(default=7, ge=1, le=90),
    principal: Principal = Depends(get_principal),
    container: Container = Depends(get_container),
) -> dict:
    return container.usage.summary(principal.tenant, days=days)
