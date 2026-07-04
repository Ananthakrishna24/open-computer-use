from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .openai import FUNCTIONS, dispatch

BASE_URL = "https://openrouter.ai/api/v1"

TOOLS = FUNCTIONS

MODELS = {
    "fast": ["google/gemma-4-26b-a4b-it"],
    "balanced": ["google/gemma-4-31b-it"],
    "capable": ["google/gemma-4-31b-it"],
}

DEFAULT_MODEL = MODELS["fast"][0]
ESCALATION_MODEL = MODELS["balanced"][0]


def pick_model(tier: str = "fast") -> str:
    if tier not in MODELS:
        raise ValueError(f"unknown tier {tier!r}; choose from {sorted(MODELS)}")
    return MODELS[tier][0]


def _load_env() -> None:
    for candidate in (Path.cwd() / ".env", Path(__file__).resolve().parents[2] / ".env"):
        try:
            content = candidate.read_text()
        except OSError:
            continue
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip("'\"")
            if key and value:
                os.environ.setdefault(key, value)
        return


def create_client(api_key: str | None = None, **kwargs: Any) -> Any:
    key = api_key or os.environ.get("OPENROUTER_API_KEY")
    if not key:
        _load_env()
        key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise RuntimeError("OpenRouter needs an API key: set OPENROUTER_API_KEY or pass api_key")
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError(
            'OpenRouter support requires the optional dependency: python -m pip install ".[openrouter]"'
        ) from exc
    return OpenAI(base_url=BASE_URL, api_key=key, **kwargs)


__all__ = [
    "BASE_URL",
    "DEFAULT_MODEL",
    "ESCALATION_MODEL",
    "MODELS",
    "TOOLS",
    "create_client",
    "dispatch",
    "pick_model",
]
