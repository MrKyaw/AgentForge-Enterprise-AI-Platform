"""Configuration parsing is explicit, validated, and environment-driven."""

from __future__ import annotations

from pathlib import Path

import pytest

from agentforge.config import (
    DEFAULT_API_KEYS,
    ApiKey,
    Settings,
    _env_bool,
    _env_float,
    _env_int,
    _env_list,
    _read_dotenv,
    parse_api_keys,
)


def test_parse_api_keys_builds_lookup() -> None:
    parsed = parse_api_keys("alpha:demo:analyst,beta:research:admin")
    assert parsed["alpha"].tenant == "demo"
    assert parsed["beta"].role == "admin"
    assert set(parsed) == {"alpha", "beta"}


def test_parse_api_keys_rejects_bad_shapes() -> None:
    with pytest.raises(ValueError, match="key:tenant:role"):
        parse_api_keys("alpha:demo")
    with pytest.raises(ValueError, match="cannot be empty"):
        parse_api_keys(":demo:analyst")
    with pytest.raises(ValueError, match="Duplicate"):
        parse_api_keys("alpha:demo:analyst,alpha:demo:admin")


def test_api_key_validates_role_and_tenant() -> None:
    with pytest.raises(ValueError, match="Invalid role"):
        ApiKey(tenant="demo", role="superuser")
    with pytest.raises(ValueError, match="tenant"):
        ApiKey(tenant="", role="admin")


def test_env_helpers_apply_defaults() -> None:
    assert _env_bool(None, True) is True
    assert _env_bool("YES", False) is True
    assert _env_bool("off", True) is False
    assert _env_float(None, 1.5) == 1.5
    assert _env_float("  ", 1.5) == 1.5
    assert _env_float("2.25", 0.0) == 2.25
    assert _env_int(None, 7) == 7
    assert _env_int("", 7) == 7
    assert _env_int("9", 0) == 9
    assert _env_list(None, ("a",)) == ("a",)
    assert _env_list("a, b ,, c", ()) == ("a", "b", "c")


def test_read_dotenv_ignores_comments_and_quotes(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "# comment\n\nAGENTFORGE_ENV=production\nQUOTED='value'\nNO_EQUALS\n",
        encoding="utf-8",
    )
    values = _read_dotenv(str(env_file))
    assert values == {"AGENTFORGE_ENV": "production", "QUOTED": "value"}
    assert _read_dotenv(str(tmp_path / "missing.env")) == {}


def test_settings_load_reads_environment_values() -> None:
    settings = Settings.load(
        env={
            "AGENTFORGE_ENV": "test",
            "AGENTFORGE_LOG_LEVEL": "debug",
            "AGENTFORGE_DB_PATH": "tmp/agent.db",
            "AGENTFORGE_DATA_DIR": "corpus",
            "AGENTFORGE_SEED_ON_STARTUP": "false",
            "AGENTFORGE_AUTH_ENABLED": "no",
            "AGENTFORGE_PORT": "9000",
            "AGENTFORGE_RATE_LIMIT_PER_MINUTE": "60",
            "AGENTFORGE_RATE_LIMIT_BURST": "5",
            "AGENTFORGE_DAILY_BUDGET_USD": "12.5",
            "AGENTFORGE_CACHE_TTL_SECONDS": "60",
            "AGENTFORGE_CACHE_MAX_ENTRIES": "10",
            "AGENTFORGE_INJECTION_THRESHOLD": "0.5",
            "AGENTFORGE_RETRIEVAL_TOP_K": "3",
            "AGENTFORGE_REDACT_OUTPUT": "0",
            "AGENTFORGE_REQUEST_TIMEOUT_SECONDS": "5",
            "AGENTFORGE_MAX_INPUT_CHARS": "1000",
            "AGENTFORGE_API_KEYS": "test-key:test:analyst",
            "AGENTFORGE_CORS_ORIGINS": "https://a.example, https://b.example",
            "OPENAI_API_KEY": "openai-key",
            "ANTHROPIC_API_KEY": "anthropic-key",
            "AZURE_OPENAI_ENDPOINT": "https://example.openai.azure.com",
            "AZURE_OPENAI_API_KEY": "azure-key",
        }
    )
    assert settings.environment == "test"
    assert settings.log_level == "DEBUG"
    assert settings.db_path == "tmp/agent.db"
    assert settings.data_dir == Path("corpus")
    assert settings.seed_on_startup is False
    assert settings.auth_enabled is False
    assert settings.port == 9000
    assert settings.rate_limit_per_minute == 60
    assert settings.rate_limit_burst == 5
    assert settings.daily_budget_usd == 12.5
    assert settings.cache_ttl_seconds == 60
    assert settings.cache_max_entries == 10
    assert settings.injection_threshold == 0.5
    assert settings.retrieval_top_k == 3
    assert settings.redact_output is False
    assert settings.request_timeout_seconds == 5
    assert settings.max_input_chars == 1000
    assert settings.api_keys["test-key"].tenant == "test"
    assert settings.cors_origins == ("https://a.example", "https://b.example")
    assert settings.openai_api_key == "openai-key"
    assert settings.anthropic_api_key == "anthropic-key"
    assert settings.azure_openai_endpoint.endswith("azure.com")
    assert "azure-key" not in repr(settings)


def test_settings_defaults_and_overrides() -> None:
    settings = Settings.load(env={})
    assert settings.db_path == "var/agentforge.db"
    assert settings.seed_on_startup is True
    assert settings.auth_enabled is True
    assert settings.api_keys == parse_api_keys(DEFAULT_API_KEYS)
    assert settings.resolved_data_dir() == Path.cwd() / "data"
    assert settings.resolved_db_path() == str(Path.cwd() / "var/agentforge.db")

    overridden = Settings.load(env={}, db_path=":memory:", data_dir=Path("/tmp/data"))
    assert overridden.resolved_db_path() == ":memory:"
    assert overridden.resolved_data_dir() == Path("/tmp/data")


def test_settings_key_helpers() -> None:
    settings = Settings.load(env={})
    assert settings.admin_key() == "demo-admin-key"
    assert settings.analyst_key() == "demo-analyst-key"

    research = Settings.load(env={"AGENTFORGE_API_KEYS": "r:research:analyst,a:other:admin"})
    assert research.admin_key() == "a"
    assert research.analyst_key() == "r"

    no_admin = Settings.load(env={"AGENTFORGE_API_KEYS": "v:demo:viewer"})
    with pytest.raises(ValueError, match="No admin"):
        no_admin.admin_key()
    with pytest.raises(ValueError, match="No admin"):
        no_admin.analyst_key()  # falls back to admin_key, which is absent
