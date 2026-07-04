from __future__ import annotations

import os
from typing import Any

from .openai import FUNCTIONS, dispatch

BASE_URL = "https://openrouter.ai/api/v1"

TOOLS = FUNCTIONS

MODELS = {
    "fast": [
        "google/gemini-2.5-flash-lite",
        "openai/gpt-4.1-nano",
        "mistralai/mistral-small-3.2-24b-instruct",
    ],
    "balanced": [
        "anthropic/claude-haiku-4.5",
        "google/gemini-2.5-flash",
        "openai/gpt-4.1-mini",
        "deepseek/deepseek-chat-v3-0324",
    ],
    "capable": [
        "anthropic/claude-sonnet-4.5",
        "google/gemini-2.5-pro",
        "openai/gpt-4.1",
    ],
}

DEFAULT_MODEL = MODELS["balanced"][0]


def pick_model(tier: str = "balanced") -> str:
    if tier not in MODELS:
        raise ValueError(f"unknown tier {tier!r}; choose from {sorted(MODELS)}")
    return MODELS[tier][0]


def create_client(api_key: str | None = None, **kwargs: Any) -> Any:
    key = api_key or os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise RuntimeError("OpenRouter needs an API key: set OPENROUTER_API_KEY or pass api_key")
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError(
            'OpenRouter support requires the optional dependency: python -m pip install ".[openrouter]"'
        ) from exc
    return OpenAI(base_url=BASE_URL, api_key=key, **kwargs)


__all__ = ["BASE_URL", "DEFAULT_MODEL", "MODELS", "TOOLS", "create_client", "dispatch", "pick_model"]
