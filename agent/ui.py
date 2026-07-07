from __future__ import annotations

import itertools
import json
import sys
import threading
import time
from typing import Any, TextIO

from ocu.schema import Action

DIM = "\033[2m"
RESET = "\033[0m"
CYAN = "\033[36m"
GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
CLEAR_LINE = "\r\033[K"

SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

PROMPT = "\x01\033[36m\x02❯\x01\033[0m\x02 "


def summarize_call(name: str, arguments: str, limit: int = 90) -> str:
    try:
        payload = json.loads(arguments or "{}")
    except ValueError:
        return f"{name}(…)"
    if name == "act":
        try:
            inner = "; ".join(Action.coerce(item).label() for item in payload.get("actions", []))
        except Exception:
            inner = json.dumps(payload.get("actions", []))
    else:
        inner = ", ".join(f"{key}={value!r}" for key, value in payload.items())
    if len(inner) > limit:
        inner = inner[: limit - 1] + "…"
    return f"{name}({inner})"


def preview_result(result: str, limit: int = 120) -> list[str]:
    lines = [line.strip() for line in result.splitlines() if line.strip()]
    if not lines:
        return []
    picked = [line for line in lines if line.startswith(("did:", "warning:", "error:"))]
    if not picked:
        picked = lines[:2]
    return [line if len(line) <= limit else line[: limit - 1] + "…" for line in picked[:3]]


class UI:
    def __init__(self, stream: TextIO = sys.stdout, *, verbose: bool = False) -> None:
        self.stream = stream
        self.verbose = verbose
        self.tty = stream.isatty()
        self._spinning = threading.Event()
        self._spinner_thread: threading.Thread | None = None
        self._label = ""
        self._turn_started: float | None = None
        self._turn_tools = 0

    def event(self, kind: str, data: dict[str, Any]) -> None:
        handler = getattr(self, f"_on_{kind}", None)
        if handler is not None:
            handler(data)

    def say(self, text: str) -> None:
        self._stop_spinner()
        self._write("\n" + text.rstrip() + "\n")
        if self._turn_started is not None:
            elapsed = time.monotonic() - self._turn_started
            self._write(self._paint(DIM, f"  {self._turn_tools} tools · {elapsed:.0f}s\n"))
            self._turn_started = None
        self._write("\n")

    def ask(self) -> str:
        return input(PROMPT if self.tty else "> ")

    def begin_turn(self) -> None:
        self._turn_started = time.monotonic()
        self._turn_tools = 0

    def interrupted(self) -> None:
        self._stop_spinner()
        self._turn_started = None
        self._write(self._paint(YELLOW, "  · interrupted\n\n"))

    def banner(self, model: str) -> None:
        self._write(
            self._paint(DIM, f"\n◆ browser agent · {model}\n  type a task · /help for commands\n\n")
        )

    def help(self) -> None:
        self._write(
            self._paint(
                DIM,
                "  <task>   run the agent on a task\n"
                "  resume   continue after you handled a manual step in the browser\n"
                "  ctrl+c   interrupt the current task\n"
                "  /quit    exit\n",
            )
        )

    def _on_thinking_start(self, data: dict[str, Any]) -> None:
        self._start_spinner(f"thinking ({data.get('model', '')})")

    def _on_thinking_end(self, data: dict[str, Any]) -> None:
        self._stop_spinner()

    def _on_tool_start(self, data: dict[str, Any]) -> None:
        self._stop_spinner()
        self._turn_tools += 1
        summary = summarize_call(data.get("name", "?"), data.get("arguments", ""))
        self._write(f"{self._paint(CYAN, '●')} {summary}\n")

    def _on_tool_end(self, data: dict[str, Any]) -> None:
        self._stop_spinner()
        result = data.get("result", "")
        color = RED if not data.get("ok", True) else DIM
        body = result.splitlines() if self.verbose else preview_result(result)
        for line in body:
            self._write(f"  {self._paint(color, '⎿ ' + line)}\n")

    def _on_nudge(self, data: dict[str, Any]) -> None:
        self._stop_spinner()
        self._write(f"  {self._paint(YELLOW, '· nudge: ' + data.get('reason', ''))}\n")

    def _on_skill(self, data: dict[str, Any]) -> None:
        self._stop_spinner()
        self._write(f"  {self._paint(GREEN, '+ skill loaded: ' + data.get('name', ''))}\n")

    def _on_escalate(self, data: dict[str, Any]) -> None:
        self._stop_spinner()
        self._write(f"  {self._paint(YELLOW, '↑ escalated to ' + data.get('model', ''))}\n")

    def _on_api_retry(self, data: dict[str, Any]) -> None:
        self._stop_spinner()
        self._write(f"  {self._paint(RED, '· api error, retrying: ' + data.get('detail', ''))}\n")

    def _paint(self, color: str, text: str) -> str:
        if not self.tty:
            return text
        return f"{color}{text}{RESET}"

    def _write(self, text: str) -> None:
        self.stream.write(text)
        self.stream.flush()

    def _start_spinner(self, label: str) -> None:
        if not self.tty:
            return
        self._stop_spinner()
        self._label = label
        self._spinning.set()
        self._spinner_thread = threading.Thread(target=self._spin, daemon=True)
        self._spinner_thread.start()

    def _stop_spinner(self) -> None:
        if self._spinner_thread is None:
            return
        self._spinning.clear()
        self._spinner_thread.join(timeout=1)
        self._spinner_thread = None
        self._write(CLEAR_LINE)

    def _spin(self) -> None:
        frames = itertools.cycle(SPINNER_FRAMES)
        while self._spinning.is_set():
            self._write(f"{CLEAR_LINE}{DIM}{next(frames)} {self._label}{RESET}")
            time.sleep(0.08)
