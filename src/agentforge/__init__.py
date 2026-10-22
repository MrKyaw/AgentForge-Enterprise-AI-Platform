"""AgentForge — a governed enterprise AI control plane.

The package exposes a small, dependency-light core that can be embedded in
services or run as the bundled FastAPI application.
"""

from agentforge.config import Settings
from agentforge.models import AgentSpec, Principal, RunRequest, RunResult

__all__ = ["AgentSpec", "Principal", "RunRequest", "RunResult", "Settings"]
__version__ = "1.0.0"
