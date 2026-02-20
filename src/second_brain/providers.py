from __future__ import annotations

from typing import Any


def _parse_model_string(model_string: str) -> tuple[str, str]:
    """Split 'provider:model_name' into (provider, model_name)."""
    if ":" not in model_string:
        raise ValueError(
            f"Model string must be 'provider:model_name' format, got '{model_string}'"
        )
    provider, _, name = model_string.partition(":")
    return provider, name


def create_model(model_string: str, foundry_url: str | None) -> Any:
    """Create a pydantic-ai model from a provider:model_name string."""
    if foundry_url is None:
        return model_string
    raise NotImplementedError("Foundry path not yet implemented")
