"""Typed errors that map cleanly onto HTTP responses."""

from __future__ import annotations

from typing import Any


class AgentForgeError(Exception):
    """Base class for expected, user-facing failures."""

    code = "agentforge_error"
    status_code = 500

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        status_code: int | None = None,
        details: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code
        if status_code is not None:
            self.status_code = status_code
        self.details = details or {}
        self.headers = headers or {}


class InvalidRequestError(AgentForgeError):
    code = "invalid_request"
    status_code = 400


class NotFoundError(AgentForgeError):
    code = "not_found"
    status_code = 404


class AuthenticationError(AgentForgeError):
    code = "authentication_required"
    status_code = 401

    def __init__(self, message: str = "A valid API key is required.") -> None:
        super().__init__(message, headers={"WWW-Authenticate": "Bearer"})


class AuthorizationError(AgentForgeError):
    code = "forbidden"
    status_code = 403


class ConflictError(AgentForgeError):
    code = "conflict"
    status_code = 409


class RateLimitError(AgentForgeError):
    code = "rate_limited"
    status_code = 429

    def __init__(self, message: str, retry_after: float = 1.0) -> None:
        super().__init__(
            message,
            details={"retry_after_seconds": round(retry_after, 2)},
            headers={"Retry-After": str(max(1, int(retry_after + 0.999)))},
        )


class BudgetExceededError(AgentForgeError):
    code = "budget_exceeded"
    status_code = 402


class PolicyViolation(AgentForgeError):
    code = "policy_violation"
    status_code = 403


class ProviderError(AgentForgeError):
    code = "provider_error"
    status_code = 502

    def __init__(
        self,
        message: str,
        *,
        retryable: bool = False,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, details=details)
        self.retryable = retryable


class ToolError(AgentForgeError):
    code = "tool_error"
    status_code = 422


class ConfigurationError(AgentForgeError):
    code = "configuration_error"
    status_code = 500
