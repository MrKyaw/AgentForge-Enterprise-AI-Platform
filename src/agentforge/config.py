"""Environment-driven configuration with secure, local-first defaults."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

VALID_ROLES = frozenset({"viewer", "analyst", "admin"})
DEFAULT_API_KEYS = (
    "demo-analyst-key:demo:analyst,"
    "demo-admin-key:demo:admin,"
    "research-analyst-key:research:analyst,"
    "viewer-key:demo:viewer"
)


def _env_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(value: str | None, default: float) -> float:
    if value is None or value.strip() == "":
        return default
    return float(value)


def _env_int(value: str | None, default: int) -> int:
    if value is None or value.strip() == "":
        return default
    return int(value)


def _env_list(value: str | None, default: tuple[str, ...]) -> tuple[str, ...]:
    if value is None:
        return default
    return tuple(part.strip() for part in value.split(",") if part.strip())


@dataclass(frozen=True, slots=True)
class ApiKey:
    """An API key principal mapping. Keys are only kept hashed at rest in production."""

    tenant: str
    role: str

    def __post_init__(self) -> None:
        if self.role not in VALID_ROLES:
            raise ValueError(f"Invalid role '{self.role}'. Expected one of {sorted(VALID_ROLES)}.")
        if not self.tenant:
            raise ValueError("API key tenant cannot be empty.")


def _read_dotenv(path: str = ".env") -> dict[str, str]:
    """Read a local .env file without adding a dependency; process env wins."""
    file_path = Path(path)
    if not file_path.exists():
        return {}
    values: dict[str, str] = {}
    for line in file_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            values[key] = value
    return values


def parse_api_keys(raw: str) -> dict[str, ApiKey]:
    """Parse ``key:tenant:role,key:tenant:role`` into a lookup table."""
    parsed: dict[str, ApiKey] = {}
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        parts = entry.split(":")
        if len(parts) != 3:
            raise ValueError("AGENTFORGE_API_KEYS entries must use the format key:tenant:role.")
        key, tenant, role = (part.strip() for part in parts)
        if not key:
            raise ValueError("API key value cannot be empty.")
        if key in parsed:
            raise ValueError(f"Duplicate API key detected for tenant '{tenant}'.")
        parsed[key] = ApiKey(tenant=tenant, role=role)
    return parsed


@dataclass(slots=True)
class Settings:
    """Runtime settings.

    ``Settings.load`` is intentionally explicit so tests can inject a complete
    environment without mutating the process environment.
    """

    environment: str = "development"
    log_level: str = "INFO"
    db_path: str = "var/agentforge.db"
    data_dir: Path = Path("data")
    seed_on_startup: bool = True
    host: str = "0.0.0.0"
    port: int = 8000
    auth_enabled: bool = True
    api_keys: dict[str, ApiKey] = field(default_factory=lambda: parse_api_keys(DEFAULT_API_KEYS))
    rate_limit_per_minute: float = 120.0
    rate_limit_burst: int = 30
    daily_budget_usd: float = 25.0
    cache_ttl_seconds: float = 300.0
    cache_max_entries: int = 512
    injection_threshold: float = 0.7
    retrieval_top_k: int = 4
    redact_output: bool = True
    request_timeout_seconds: float = 30.0
    max_input_chars: int = 8000
    model_retry_attempts: int = 2
    model_retry_backoff_seconds: float = 0.05
    cors_origins: tuple[str, ...] = (
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    )
    openai_api_key: str = field(default="", repr=False)
    openai_base_url: str = "https://api.openai.com/v1"
    anthropic_api_key: str = field(default="", repr=False)
    azure_openai_endpoint: str = field(default="", repr=False)
    azure_openai_api_key: str = field(default="", repr=False)
    azure_openai_api_version: str = "2024-10-21"
    azure_openai_deployment: str = "gpt-4o"

    @classmethod
    def load(
        cls,
        env: Mapping[str, str] | None = None,
        **overrides: Any,
    ) -> Settings:
        """Load settings from a mapping (defaults to ``.env`` + ``os.environ``)."""
        source = {**_read_dotenv(), **os.environ} if env is None else env
        raw_keys = source.get("AGENTFORGE_API_KEYS")
        values: dict[str, Any] = {
            "environment": source.get("AGENTFORGE_ENV", "development"),
            "log_level": source.get("AGENTFORGE_LOG_LEVEL", "INFO").upper(),
            "db_path": source.get("AGENTFORGE_DB_PATH", "var/agentforge.db"),
            "data_dir": Path(source.get("AGENTFORGE_DATA_DIR", "data")),
            "seed_on_startup": _env_bool(source.get("AGENTFORGE_SEED_ON_STARTUP"), True),
            "host": source.get("AGENTFORGE_HOST", "0.0.0.0"),
            "port": _env_int(source.get("AGENTFORGE_PORT"), 8000),
            "auth_enabled": _env_bool(source.get("AGENTFORGE_AUTH_ENABLED"), True),
            "api_keys": parse_api_keys(DEFAULT_API_KEYS if raw_keys is None else raw_keys),
            "rate_limit_per_minute": _env_float(
                source.get("AGENTFORGE_RATE_LIMIT_PER_MINUTE"), 120.0
            ),
            "rate_limit_burst": _env_int(source.get("AGENTFORGE_RATE_LIMIT_BURST"), 30),
            "daily_budget_usd": _env_float(source.get("AGENTFORGE_DAILY_BUDGET_USD"), 25.0),
            "cache_ttl_seconds": _env_float(source.get("AGENTFORGE_CACHE_TTL_SECONDS"), 300.0),
            "cache_max_entries": _env_int(source.get("AGENTFORGE_CACHE_MAX_ENTRIES"), 512),
            "injection_threshold": _env_float(source.get("AGENTFORGE_INJECTION_THRESHOLD"), 0.7),
            "retrieval_top_k": _env_int(source.get("AGENTFORGE_RETRIEVAL_TOP_K"), 4),
            "redact_output": _env_bool(source.get("AGENTFORGE_REDACT_OUTPUT"), True),
            "request_timeout_seconds": _env_float(
                source.get("AGENTFORGE_REQUEST_TIMEOUT_SECONDS"), 30.0
            ),
            "max_input_chars": _env_int(source.get("AGENTFORGE_MAX_INPUT_CHARS"), 8000),
            "openai_api_key": source.get("OPENAI_API_KEY", ""),
            "openai_base_url": source.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            "anthropic_api_key": source.get("ANTHROPIC_API_KEY", ""),
            "azure_openai_endpoint": source.get("AZURE_OPENAI_ENDPOINT", ""),
            "azure_openai_api_key": source.get("AZURE_OPENAI_API_KEY", ""),
            "azure_openai_api_version": source.get("AZURE_OPENAI_API_VERSION", "2024-10-21"),
            "azure_openai_deployment": source.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o"),
            "cors_origins": _env_list(
                source.get("AGENTFORGE_CORS_ORIGINS"),
                ("http://localhost:8000", "http://127.0.0.1:8000"),
            ),
        }
        values.update(overrides)
        return cls(**values)

    def admin_key(self) -> str:
        """Return a configured admin key, used by CLI commands and the smoke demo."""
        for key, principal in self.api_keys.items():
            if principal.role == "admin" and principal.tenant == "demo":
                return key
        for key, principal in self.api_keys.items():
            if principal.role == "admin":
                return key
        raise ValueError("No admin API key configured.")

    def analyst_key(self) -> str:
        """Return a configured analyst key, used by the CLI and dashboard."""
        for key, principal in self.api_keys.items():
            if principal.role == "analyst":
                return key
        return self.admin_key()

    def resolved_data_dir(self) -> Path:
        """Resolve the data directory relative to the current working directory."""
        return self.data_dir if self.data_dir.is_absolute() else Path.cwd() / self.data_dir

    def resolved_db_path(self) -> str:
        """Resolve a file database path; ``:memory:`` is passed through untouched."""
        if self.db_path == ":memory:":
            return self.db_path
        path = Path(self.db_path)
        return str(path if path.is_absolute() else Path.cwd() / path)
