"""API-key authentication and role checks."""

from __future__ import annotations

import pytest

from agentforge.auth import Authenticator
from agentforge.config import Settings
from agentforge.errors import AuthenticationError, AuthorizationError
from agentforge.models import Principal


@pytest.fixture()
def auth() -> Authenticator:
    return Authenticator(Settings.load(env={}))


def test_authenticates_configured_keys(auth: Authenticator) -> None:
    principal = auth.authenticate("demo-admin-key")
    assert principal.tenant == "demo"
    assert principal.role == "admin"
    assert principal.is_admin is True
    assert principal.key_id.startswith("key_")
    assert principal.key_id == auth.authenticate("demo-admin-key").key_id
    assert len(principal.key_id) == len("key_") + 10


def test_missing_or_invalid_keys_are_rejected(auth: Authenticator) -> None:
    with pytest.raises(AuthenticationError):
        auth.authenticate(None)
    with pytest.raises(AuthenticationError):
        auth.authenticate("")
    with pytest.raises(AuthenticationError, match="not valid"):
        auth.authenticate("wrong-key")


def test_auth_disabled_returns_demo_admin() -> None:
    settings = Settings.load(env={"AGENTFORGE_AUTH_ENABLED": "false"})
    principal = Authenticator(settings).authenticate(None)
    assert principal == Principal(tenant="demo", role="admin", key_id="auth-disabled")


def test_role_requirements(auth: Authenticator) -> None:
    admin = auth.authenticate("demo-admin-key")
    viewer = auth.authenticate("viewer-key")

    Authenticator.require_role(admin, {"admin"})
    Authenticator.require_admin(admin)
    with pytest.raises(AuthorizationError, match="not permitted"):
        Authenticator.require_role(viewer, {"admin"})
    with pytest.raises(AuthorizationError):
        Authenticator.require_admin(viewer)
