from __future__ import annotations


def _parse_model_string(model_string: str) -> tuple[str, str]:
    """Split 'provider:model_name' into (provider, model_name)."""
    if ":" not in model_string:
        raise ValueError(
            f"Model string must be 'provider:model_name' format, got '{model_string}'"
        )
    provider, _, name = model_string.partition(":")
    return provider, name
