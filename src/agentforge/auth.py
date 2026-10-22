"""API-key authentication with constant-time comparison and tenant isolation."""

from __future__ import annotations

import hmac
from collections.abc import Iterable
from hashlib import sha256

from agentforge.config import Settings
from agentforge.errors import AuthenticationError, AuthorizationError
from agentforge.models import Principal


class Authenticator:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def authenticate(self, raw_key: str | None) -> Principal:
        if not self.settings.auth_enabled:
            # Explicit local-development escape hatch. Never enable this in production.
            return Principal(tenant="demo", role="admin", key_id="auth-disabled")
        if not raw_key:
            raise AuthenticationError("A valid API key is required in X-API-Key or Bearer auth.")
        matched: tuple[str, object] | None = None
        for configured_key, config in self.settings.api_keys.items():
            if hmac.compare_digest(raw_key, configured_key):
                matched = (configured_key, config)
        if matched is None:
            raise AuthenticationError("The supplied API key is not valid.")
        configured_key, config = matched
        return Principal(
            tenant=config.tenant,  # type: ignore[attr-defined]
            role=config.role,  # type: ignore[attr-defined]
            key_id=f"key_{sha256(configured_key.encode()).hexdigest()[:10]}",
        )

    @staticmethod
    def require_role(principal: Principal, allowed: Iterable[str]) -> None:
        allowed_set = set(allowed)
        if principal.role not in allowed_set:
            raise AuthorizationError(
                f"Role '{principal.role}' is not permitted. Required: {sorted(allowed_set)}."
            )

    @staticmethod
    def require_admin(principal: Principal) -> None:
        Authenticator.require_role(principal, {"admin"})
