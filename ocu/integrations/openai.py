from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

FUNCTIONS = [
    {
        "type": "function",
        "function": {
            "name": "observe",
            "description": (
                "Refresh the screen observation. full lists elements for acting, "
                "text returns the readable page text for reading content, region zooms."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "mode": {"type": "string", "enum": ["full", "text", "region"], "default": "full"},
                    "region": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "minItems": 4,
                        "maxItems": 4,
                    },
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "act",
            "description": (
                "Execute one or more grounded actions and return the screen delta. "
                "type replaces whatever text the field already contains. "
                "goto navigates to the URL given in text; back returns to the previous page. "
                "drag presses at coordinate (or target center) and releases at to."
            ),
            "parameters": {
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
    },
]

TOOLS = FUNCTIONS


def dispatch(env: Any, tool_call: Any) -> str:
    try:
        name, payload = _name_and_payload(tool_call)
    except ValueError as exc:
        _repair_arguments(tool_call)
        return f"error: {exc}"
    try:
        if name == "observe":
            region = payload.get("region")
            return env.observe(mode=payload.get("mode", "full"), region=tuple(region) if region else None).text
        if name == "act":
            return env.act_batch(
                payload.get("actions", []),
                guard=payload.get("guard", "abort_on_unexpected_change"),
            ).text
        return f"error: unknown tool {name!r}"
    except Exception as exc:
        return f"error: {exc}"


def _repair_arguments(tool_call: Any) -> None:
    function = tool_call.get("function") if isinstance(tool_call, Mapping) else getattr(tool_call, "function", None)
    holder = function if function is not None else tool_call
    if isinstance(holder, Mapping):
        if isinstance(holder.get("arguments"), str):
            try:
                holder["arguments"] = "{}"
            except TypeError:
                pass
    elif isinstance(getattr(holder, "arguments", None), str):
        holder.arguments = "{}"


def _name_and_payload(tool_call: Any) -> tuple[str, dict[str, Any]]:
    if isinstance(tool_call, Mapping):
        if "function" in tool_call:
            function = tool_call["function"]
            return str(function.get("name", "")), _loads(function.get("arguments", {}))
        return str(tool_call.get("name", "")), _loads(tool_call.get("arguments", tool_call.get("input", {})))

    function = getattr(tool_call, "function", None)
    if function is not None:
        return str(getattr(function, "name", "")), _loads(getattr(function, "arguments", {}))
    return str(getattr(tool_call, "name", "")), _loads(getattr(tool_call, "arguments", {}))


def _loads(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        try:
            return dict(json.loads(value or "{}"))
        except ValueError as exc:
            raise ValueError(
                "tool arguments were not valid JSON (likely truncated); retry with a smaller batch of actions"
            ) from exc
    return dict(value or {})
