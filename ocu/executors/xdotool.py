from __future__ import annotations

import subprocess
from time import sleep
from typing import Any, Callable

from ..resolve import ResolvedTarget
from ..schema import Action
from .cdp import _point

KEY_MAP = {
    "enter": "Return",
    "return": "Return",
    "escape": "Escape",
    "esc": "Escape",
    "backspace": "BackSpace",
    "delete": "Delete",
    "del": "Delete",
    "tab": "Tab",
    "space": "space",
    "arrowup": "Up",
    "arrowdown": "Down",
    "arrowleft": "Left",
    "arrowright": "Right",
    "up": "Up",
    "down": "Down",
    "left": "Left",
    "right": "Right",
    "pageup": "Prior",
    "pagedown": "Next",
    "home": "Home",
    "end": "End",
    "insert": "Insert",
    "control": "ctrl",
    "ctrl": "ctrl",
    "alt": "alt",
    "shift": "shift",
    "meta": "super",
    "cmd": "super",
    "super": "super",
}

SCROLL_STEP_PX = 120
TYPE_DELAY_MS = 12


class XdotoolExecutor:
    def __init__(self, *, runner: Callable[[list[str]], Any] | None = None) -> None:
        self._runner = runner or _default_runner

    def execute(self, action: Action, target: ResolvedTarget) -> None:
        if action.verb == "click":
            self._click(target)
        elif action.verb == "type":
            self._type(action, target)
        elif action.verb == "press":
            self._press(action)
        elif action.verb == "scroll":
            self._scroll(action, target)
        elif action.verb == "drag":
            self._drag(action, target)
        elif action.verb == "wait":
            self._wait(action)
        elif action.verb in {"observe", "done"}:
            return
        else:
            raise ValueError(f"unsupported action verb {action.verb!r} on the desktop")

    def _click(self, target: ResolvedTarget) -> None:
        if target.coordinate is None:
            raise ValueError("click requires a resolved coordinate")
        x, y = target.coordinate
        self._run("mousemove", "--sync", x, y, "click", "1")

    def _type(self, action: Action, target: ResolvedTarget) -> None:
        if target.coordinate is not None:
            self._click(target)
        self._run("key", "--clearmodifiers", "ctrl+a")
        text = action.text or ""
        if text:
            self._run("type", "--clearmodifiers", "--delay", TYPE_DELAY_MS, "--", text)
        else:
            self._run("key", "--clearmodifiers", "Delete")

    def _press(self, action: Action) -> None:
        key = action.text or action.metadata.get("key") or action.metadata.get("press")
        if not key:
            raise ValueError('press needs the key name in text: {"verb": "press", "text": "Escape"}')
        combo = "+".join(_keysym(part) for part in str(key).split("+"))
        self._run("key", "--clearmodifiers", combo)

    def _scroll(self, action: Action, target: ResolvedTarget) -> None:
        if target.coordinate is not None:
            x, y = target.coordinate
            self._run("mousemove", "--sync", x, y)
        dx = int(action.metadata.get("dx", action.metadata.get("delta_x", 0)))
        dy = int(action.metadata.get("dy", action.metadata.get("delta_y", 500)))
        if dy:
            self._run("click", "--repeat", _repeats(dy), "5" if dy > 0 else "4")
        if dx:
            self._run("click", "--repeat", _repeats(dx), "7" if dx > 0 else "6")

    def _drag(self, action: Action, target: ResolvedTarget) -> None:
        if target.coordinate is None:
            raise ValueError("drag requires a start: coordinate [x, y] (or a target id)")
        end = _point(action.metadata.get("to") or action.metadata.get("end"))
        if end is None:
            raise ValueError('drag needs both corners: {"verb": "drag", "coordinate": [x1, y1], "to": [x2, y2]}')
        start_x, start_y = target.coordinate
        end_x, end_y = end
        self._run(
            "mousemove", "--sync", start_x, start_y,
            "mousedown", "1",
            "mousemove", "--sync", end_x, end_y,
            "mouseup", "1",
        )

    def _wait(self, action: Action) -> None:
        milliseconds = int(action.metadata.get("ms", action.metadata.get("milliseconds", 500)))
        sleep(milliseconds / 1000)

    def _run(self, *args: Any) -> Any:
        command = ["xdotool", *(str(arg) for arg in args)]
        try:
            result = self._runner(command)
        except FileNotFoundError as exc:
            raise RuntimeError(
                "xdotool not found: install it (e.g. sudo apt install xdotool) and run under X11"
            ) from exc
        code = getattr(result, "returncode", 0)
        if code != 0:
            stderr = getattr(result, "stderr", "") or ""
            if isinstance(stderr, bytes):
                stderr = stderr.decode(errors="replace")
            detail = stderr.strip() or f"exit code {code}"
            raise RuntimeError(f"xdotool failed ({' '.join(command)}): {detail}")
        return result


def _default_runner(command: list[str]) -> Any:
    return subprocess.run(command, capture_output=True, text=True)


def _keysym(part: str) -> str:
    stripped = part.strip()
    lowered = stripped.lower()
    if lowered in KEY_MAP:
        return KEY_MAP[lowered]
    if len(stripped) == 1:
        return stripped
    if lowered.startswith("f") and lowered[1:].isdigit():
        return lowered.upper()
    return stripped


def _repeats(delta: int) -> int:
    return max(1, round(abs(delta) / SCROLL_STEP_PX))
