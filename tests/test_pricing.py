"""Model catalogue, aliases, and illustrative cost math."""

from __future__ import annotations

import pytest

from agentforge.errors import InvalidRequestError
from agentforge.gateway.pricing import DEFAULT_MODELS, ModelInfo, PricingCatalog


def test_model_metadata_is_complete() -> None:
    assert len(DEFAULT_MODELS) == 5
    assert all(model.id and model.provider for model in DEFAULT_MODELS)
    assert all(model.context_window > 0 for model in DEFAULT_MODELS)


def test_resolve_alias_and_exact_model() -> None:
    catalog = PricingCatalog()
    assert [model.id for model in catalog.resolve("fast")] == ["gpt-4.1-mini", "local-grounded"]
    assert [model.id for model in catalog.resolve("private")] == ["local-grounded"]
    assert [model.id for model in catalog.resolve("gpt-4.1")] == ["gpt-4.1"]
    assert catalog.get("gpt-4.1").provider == "openai"
    assert catalog.get("missing") is None


def test_unknown_model_is_rejected_with_guidance() -> None:
    with pytest.raises(InvalidRequestError) as excinfo:
        PricingCatalog().resolve("unknown-model")
    assert "available_models" in excinfo.value.details
    assert "aliases" in excinfo.value.details


def test_alias_validation() -> None:
    with pytest.raises(ValueError, match="unknown models"):
        PricingCatalog(aliases={"broken": ["missing-model"]})


def test_cost_calculation() -> None:
    catalog = PricingCatalog()
    assert catalog.calculate("gpt-4.1", 1_000_000, 500_000) == 6.0
    assert catalog.calculate("gpt-4.1-mini", 1000, 1000) == pytest.approx(0.002)
    assert catalog.calculate("local-grounded", 1_000_000, 1_000_000) == 0.0
    assert catalog.calculate("unknown", 100, 100) == 0.0


def test_public_models_marks_availability() -> None:
    catalog = PricingCatalog([ModelInfo("m1", "local", "Local", 0, 0, 1000)], aliases={})
    models = catalog.public_models({"local"})
    assert models[0]["available"] is True
    assert models[0]["id"] == "m1"
    assert catalog.public_models({"openai"})[0]["available"] is False
