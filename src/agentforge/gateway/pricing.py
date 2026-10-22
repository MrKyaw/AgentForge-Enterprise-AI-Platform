"""Model catalog, aliases, and illustrative cost accounting.

Prices are configuration examples, not contractual vendor rates. Replace them
with the rates in your enterprise agreement before production use.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, dataclass

from agentforge.errors import InvalidRequestError


@dataclass(frozen=True, slots=True)
class ModelInfo:
    id: str
    provider: str
    display_name: str
    input_per_million: float
    output_per_million: float
    context_window: int
    residency: str = "global"
    tier: str = "balanced"
    supports_tools: bool = True

    def public_dict(self, available: bool) -> dict[str, object]:
        data = asdict(self)
        data["available"] = available
        return data


DEFAULT_MODELS: tuple[ModelInfo, ...] = (
    ModelInfo(
        id="local-grounded",
        provider="local",
        display_name="Grounded Local (offline)",
        input_per_million=0.0,
        output_per_million=0.0,
        context_window=32_768,
        residency="local",
        tier="economy",
    ),
    ModelInfo(
        id="gpt-4.1-mini",
        provider="openai",
        display_name="GPT-4.1 mini",
        input_per_million=0.40,
        output_per_million=1.60,
        context_window=1_000_000,
        residency="global",
        tier="fast",
    ),
    ModelInfo(
        id="gpt-4.1",
        provider="openai",
        display_name="GPT-4.1",
        input_per_million=2.00,
        output_per_million=8.00,
        context_window=1_000_000,
        residency="global",
        tier="reasoning",
    ),
    ModelInfo(
        id="claude-sonnet-4-5",
        provider="anthropic",
        display_name="Claude Sonnet 4.5",
        input_per_million=3.00,
        output_per_million=15.00,
        context_window=200_000,
        residency="global",
        tier="balanced",
    ),
    ModelInfo(
        id="azure-gpt-4o",
        provider="azure-openai",
        display_name="Azure OpenAI GPT-4o",
        input_per_million=2.50,
        output_per_million=10.00,
        context_window=128_000,
        residency="canada",
        tier="balanced",
    ),
)

DEFAULT_ALIASES: dict[str, list[str]] = {
    "fast": ["gpt-4.1-mini", "local-grounded"],
    "balanced": ["claude-sonnet-4-5", "azure-gpt-4o", "gpt-4.1-mini", "local-grounded"],
    "reasoning": ["gpt-4.1", "claude-sonnet-4-5", "local-grounded"],
    "private": ["local-grounded"],
    "economy": ["local-grounded"],
}


class PricingCatalog:
    def __init__(
        self,
        models: Iterable[ModelInfo] = DEFAULT_MODELS,
        aliases: dict[str, list[str]] | None = None,
    ) -> None:
        self.models = {model.id: model for model in models}
        self.aliases = dict(DEFAULT_ALIASES if aliases is None else aliases)
        for alias, members in self.aliases.items():
            missing = [member for member in members if member not in self.models]
            if missing:
                raise ValueError(f"Alias '{alias}' references unknown models: {missing}")

    def resolve(self, name: str) -> list[ModelInfo]:
        """Resolve an alias or model id to an ordered fallback chain."""
        if name in self.aliases:
            return [self.models[model_id] for model_id in self.aliases[name]]
        if name in self.models:
            return [self.models[name]]
        raise InvalidRequestError(
            f"Unknown model or alias '{name}'.",
            details={"available_models": sorted(self.models), "aliases": sorted(self.aliases)},
        )

    def get(self, model_id: str) -> ModelInfo | None:
        return self.models.get(model_id)

    def calculate(self, model_id: str, prompt_tokens: int, completion_tokens: int) -> float:
        model = self.models.get(model_id)
        if model is None:
            return 0.0
        return round(
            (prompt_tokens / 1_000_000) * model.input_per_million
            + (completion_tokens / 1_000_000) * model.output_per_million,
            8,
        )

    def public_models(self, available_providers: set[str]) -> list[dict[str, object]]:
        return [
            model.public_dict(available=model.provider in available_providers)
            for model in self.models.values()
        ]
