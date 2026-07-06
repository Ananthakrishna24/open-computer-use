from __future__ import annotations

import subprocess
from time import sleep
from typing import Any, Callable

from ..resolve import ResolvedTarget
from ..schema import Action
from .cdp import _point
from .xdotool import TYPE_DELAY_MS, _repeats

KEYCODES = {
    "esc": 1, "escape": 1,
    "1": 2, "2": 3, "3": 4, "4": 5, "5": 6, "6": 7, "7": 8, "8": 9, "9": 10, "0": 11,
    "minus": 12, "-": 12, "equal": 13, "=": 13,
    "backspace": 14, "tab": 15,
    "q": 16, "w": 17, "e": 18, "r": 19, "t": 20, "y": 21, "u": 22, "i": 23, "o": 24, "p": 25,
    "[": 26, "]": 27,
    "enter": 28, "return": 28,
    "ctrl": 29, "control": 29,
    "a": 30, "s": 31, "d": 32, "f": 33, "g": 34, "h": 35, "j": 36, "k": 37, "l": 38,
    ";": 39, "'": 40, "`": 41,
    "shift": 42,
    "\\": 43,
    "z": 44, "x": 45, "c": 46, "v": 47, "b": 48, "n": 49, "m": 50,
    ",": 51, ".": 52, "/": 53,
    "alt": 56, "space": 57, " ": 57, "capslock": 58,
    "f1": 59, "f2": 60, "f3": 61, "f4": 62, "f5": 63, "f6": 64, "f7": 65, "f8": 66,
    "f9": 67, "f10": 68, "f11": 87, "f12": 88,
    "home": 102,
    "up": 103, "arrowup": 103,
    "pageup": 104,
    "left": 105, "arrowleft": 105,
    "right": 106, "arrowright": 106,
    "end": 107,
    "down": 108, "arrowdown": 108,
    "pagedown": 109,
    "insert": 110,
    "delete": 111, "del": 111,
    "meta": 125, "super": 125, "cmd": 125,
}

LEFT_PRESS = "0x40"
LEFT_RELEASE = "0x80"
LEFT_CLICK = "0xC0"


class YdotoolExecutor:
    def __init__(self, *, runner: Callable[[list[str]], Any] | None = None, scale: float = 1.0) -> None:
        self._runner = runner or _default_runner
        self.scale = scale

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

    def _move(self, x: int, y: int) -> None:
        self._run("mousemove", "-a", "-x", round(x * self.scale), "-y", round(y * self.scale))

    def _click(self, target: ResolvedTarget) -> None:
        if target.coordinate is None:
            raise ValueError("click requires a resolved coordinate")
        self._move(*target.coordinate)
        self._run("click", LEFT_CLICK)

    def _type(self, action: Action, target: ResolvedTarget) -> None:
        if target.coordinate is not None:
            self._click(target)
        self._key_combo("ctrl+a")
        text = action.text or ""
        if text:
            self._run("type", "-d", TYPE_DELAY_MS, "--", text)
        else:
            self._key_combo("delete")

    def _press(self, action: Action) -> None:
        key = action.text or action.metadata.get("key") or action.metadata.get("press")
        if not key:
            raise ValueError('press needs the key name in text: {"verb": "press", "text": "Escape"}')
        self._key_combo(str(key))

    def _key_combo(self, combo: str) -> None:
        codes = [_keycode(part) for part in combo.split("+")]
        presses = [f"{code}:1" for code in codes]
        releases = [f"{code}:0" for code in reversed(codes)]
        self._run("key", *presses, *releases)

    def _scroll(self, action: Action, target: ResolvedTarget) -> None:
        if target.coordinate is not None:
            self._move(*target.coordinate)
        dx = int(action.metadata.get("dx", action.metadata.get("delta_x", 0)))
        dy = int(action.metadata.get("dy", action.metadata.get("delta_y", 500)))
        if dy:
            self._run("mousemove", "-w", "-x", "0", "-y", -_repeats(dy) if dy > 0 else _repeats(dy))
        if dx:
            self._run("mousemove", "-w", "-x", _repeats(dx) if dx > 0 else -_repeats(dx), "-y", "0")

    def _drag(self, action: Action, target: ResolvedTarget) -> None:
        if target.coordinate is None:
            raise ValueError("drag requires a start: coordinate [x, y] (or a target id)")
        end = _point(action.metadata.get("to") or action.metadata.get("end"))
        if end is None:
            raise ValueError('drag needs both corners: {"verb": "drag", "coordinate": [x1, y1], "to": [x2, y2]}')
        self._move(*target.coordinate)
        self._run("click", LEFT_PRESS)
        self._move(*end)
        self._run("click", LEFT_RELEASE)

    def _wait(self, action: Action) -> None:
        milliseconds = int(action.metadata.get("ms", action.metadata.get("milliseconds", 500)))
        sleep(milliseconds / 1000)

    def _run(self, *args: Any) -> Any:
        command = ["ydotool", *(str(arg) for arg in args)]
        try:
            result = self._runner(command)
        except FileNotFoundError as exc:
            raise RuntimeError(
                "ydotool not found: install it (e.g. sudo apt install ydotool) and start "
                "the ydotoold daemon (sudo systemctl enable --now ydotool)"
            ) from exc
        code = getattr(result, "returncode", 0)
        if code != 0:
            stderr = getattr(result, "stderr", "") or ""
            if isinstance(stderr, bytes):
                stderr = stderr.decode(errors="replace")
            detail = stderr.strip() or f"exit code {code}"
            raise RuntimeError(f"ydotool failed ({' '.join(command)}): {detail}")
        return result


def _default_runner(command: list[str]) -> Any:
    return subprocess.run(command, capture_output=True, text=True)


def _keycode(part: str) -> int:
    lowered = part.strip().lower()
    if lowered in KEYCODES:
        return KEYCODES[lowered]
    raise ValueError(
        f"unknown key {part!r} for ydotool: use names like Enter, Escape, Tab, Ctrl+A, F5"
    )
