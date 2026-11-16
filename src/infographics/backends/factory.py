"""Build a backend from a model config file in configs/models/."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .base import Backend

# Keys every model config must pin, so a run can be reproduced.
REQUIRED_KEYS = {"name", "backend", "model", "checkpoint", "quantization"}


def load_model_config(path: str | Path) -> dict[str, Any]:
    config = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    missing = REQUIRED_KEYS - config.keys()
    if missing:
        raise ValueError(f"{path}: missing {sorted(missing)}")
    if "FILL_IN" in str(config["checkpoint"]):
        raise ValueError(f"{path}: pin the exact model version in 'checkpoint' before running")
    return config


def make_backend(config: dict[str, Any]) -> Backend:
    kind = config["backend"]
    if kind == "openai_compatible":
        from .openai_compatible import OpenAICompatibleBackend

        return OpenAICompatibleBackend(
            model=config["model"],
            base_url=config.get("base_url"),
            api_key_env=config.get("api_key_env"),
            max_tokens=config.get("max_tokens", 16384),
            extra_body=config.get("extra_body"),
            max_tokens_param=config.get("max_tokens_param", "max_tokens"),
            send_seed=config.get("send_seed", True),
        )
    if kind == "anthropic":
        from .anthropic_backend import AnthropicBackend

        return AnthropicBackend(
            model=config["model"],
            api_key_env=config.get("api_key_env", "ANTHROPIC_API_KEY"),
            max_tokens=config.get("max_tokens", 32000),
            effort=config.get("effort"),
        )
    raise ValueError(f"unknown backend {kind!r}")


def temperature_for(config: dict[str, Any], plan_default: float) -> float | None:
    """The plan's temperature, unless the config overrides it.

    `temperature: null` in a config means the provider's default, for models that reject any
    other value (Claude Opus 5.5; GPT-5.5 with reasoning on).
    """
    return config.get("temperature", plan_default)
