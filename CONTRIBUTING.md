# Contributing

## Development setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Workflow

1. Create a branch from `main`.
2. Make a focused change.
3. Add or update tests.
4. Run `make check` (lint + tests).
5. Run `make eval` if you touched retrieval, policy, or synthesis.
6. Open a pull request using the template.

## Standards

- Python 3.11+ compatible. Use type hints.
- Follow `ruff` configuration in `pyproject.toml`.
- Line length 100.
- Tests must be deterministic and isolated.
- No network access in tests.
- Document user-visible changes in `CHANGELOG.md`.
- Keep the offline demo working: `agentforge demo` must pass without keys.

## Commit style

Use conventional commits where practical:

- `feat:` new capability
- `fix:` bug fix
- `docs:` documentation
- `test:` tests
- `refactor:` internal change
- `chore:` tooling

## Adding an agent

1. Add an `AgentSpec` to `builtin_agents()` in `src/agentforge/agents/registry.py`.
2. Ensure every tool referenced exists in `build_default_tools`.
3. Add tests for tool references and a runtime test.
4. Add at least one golden-set case if the agent is user-facing.
5. Document the agent in the README table.

## Adding a provider

1. Implement `ModelProvider` in `gateway/providers.py`.
2. Register it in `ProviderRegistry.from_settings`.
3. Add a `ModelInfo` entry and alias membership in `pricing.py`.
4. Add unit tests with a mocked HTTP transport.
5. Document configuration in `.env.example` and README.

## Review expectations

- Small, focused pull requests.
- Tests for behaviour changes.
- No reduction in coverage below the gate.
- Honest documentation of limitations.
