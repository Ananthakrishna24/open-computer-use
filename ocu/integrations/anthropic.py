from __future__ import annotations

from collections.abc import Mapping
from typing import Any

TOOLS = [
    {
        "name": "observe",
        "description": (
            "Refresh the screen observation. full lists elements for acting, "
            "text returns the readable page text for reading content, region zooms."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "mode": {"type": "string", "enum": ["full", "text", "region"], "default": "full"},
                "region": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "minItems": 4,
                    "maxItems": 4,
                    "description": "[x, y, width, height] in observation pixels; required for region mode.",
                },
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "act",
        "description": (
            "Execute one or more grounded actions and return the screen delta. "
            "goto navigates to the URL given in text; back returns to the previous page. "
            "drag presses at coordinate (or target center) and releases at to."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "actions": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "properties": {
                            "verb": {
                                "type": "string",
                                "enum": [
                                    "click",
                                    "type",
                                    "press",
                                    "scroll",
                                    "drag",
                                    "wait",
                                    "goto",
                                    "back",
                                    "observe",
                                    "done",
                                ],
                            },
                            "target": {"type": ["integer", "null"]},
                            "coordinate": {
                                "type": ["array", "null"],
                                "items": {"type": "integer"},
                                "minItems": 2,
                                "maxItems": 2,
                            },
                            "to": {
                                "type": ["array", "null"],
                                "items": {"type": "integer"},
                                "minItems": 2,
                                "maxItems": 2,
                                "description": "Drag end point [x, y].",
                            },
                            "text": {"type": ["string", "null"]},
                        },
                        "required": ["verb"],
                        "additionalProperties": True,
                    },
                },
                "guard": {
                    "type": "string",
                    "enum": ["abort_on_unexpected_change", "none"],
                    "default": "abort_on_unexpected_change",
                },
            },
            "required": ["actions"],
            "additionalProperties": False,
        },
    },
]


def dispatch(env: Any, block: Any) -> str:
    name, payload = _name_and_payload(block)
    try:
        if name == "observe":
            mode = payload.get("mode", "full")
            region = payload.get("region")
            return env.observe(mode=mode, region=tuple(region) if region else None).text
        if name == "act":
            return env.act_batch(
                payload.get("actions", []),
                guard=payload.get("guard", "abort_on_unexpected_change"),
            ).text
        return f"error: unknown tool {name!r}"
    except Exception as exc:
        return f"error: {exc}"


def _name_and_payload(block: Any) -> tuple[str, dict[str, Any]]:
    if isinstance(block, Mapping):
        return str(block.get("name", "")), dict(block.get("input") or {})
    return str(getattr(block, "name", "")), dict(getattr(block, "input", {}) or {})
