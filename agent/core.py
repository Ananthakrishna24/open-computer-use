from __future__ import annotations

import json
from collections import deque
from pathlib import Path
from time import sleep
from typing import Any, Callable

from ocu import Browser
from ocu.integrations.openrouter import create_client, dispatch, pick_model

from .browser import DEFAULT_PROFILE, launch_page, looks_blocked, page_text, read_page
from .prompts import (
    AGENT_TOOLS,
    BLOCKED_HANDOFF,
    EMPTY_REPLY_RETRY,
    LEAKED_TOOL_CALL_RETRY,
    QUESTION_REPLY_RETRY,
    REPEAT_WARNING,
    SYSTEM_PROMPT,
)
from .skills import SKILL_TOOL, SKILLS

DEFAULT_MODEL = pick_model("fast")
ESCALATION_MODEL = pick_model("balanced")

EventHandler = Callable[[str, dict[str, Any]], None]


def act_signature(name: str, arguments: str) -> str:
    try:
        payload = json.loads(arguments or "{}")
    except ValueError:
        payload = arguments
    return name + json.dumps(payload, sort_keys=True, default=str)


def is_failure(result: str) -> bool:
    return result.startswith("error:") or "aborted at step" in result


def leaks_tool_call(text: str) -> bool:
    lowered = text.lower()
    return "<|" in lowered or "tool_call" in lowered or lowered.startswith(("act {", "read {", "observe {"))


def asks_user_to_decide(text: str) -> bool:
    lowered = text.lower()
    markers = (
        "what would you like",
        "would you like me",
        "would you like to",
        "please provide",
        "which result",
        "what do you want",
        "let me know if",
        "shall i",
        "should i",
    )
    return any(marker in lowered for marker in markers)


class Agent:
    def __init__(
        self,
        start_url: str = "https://www.bing.com",
        *,
        model: str = DEFAULT_MODEL,
        escalation_model: str = ESCALATION_MODEL,
        escalate_after: int = 2,
        budget: int = 1800,
        max_steps: int = 40,
        max_tokens: int = 700,
        temperature: float = 0.2,
        history_limit: int = 80,
        headless: bool = False,
        profile_dir: str | Path = DEFAULT_PROFILE,
        block_resources: bool = False,
        slow_mo: int = 60,
        on_event: EventHandler | None = None,
    ) -> None:
        self.client = create_client()
        self.model = model
        self.escalation_model = escalation_model
        self.escalate_after = escalate_after
        self.max_steps = max_steps
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.history_limit = history_limit
        self.on_event = on_event
        self.tools: list[Any] = AGENT_TOOLS + [SKILL_TOOL]
        self.skill_handlers: dict[str, Any] = {}
        self.messages: list[Any] = [{"role": "system", "content": SYSTEM_PROMPT}]
        self._playwright, self._context, page = launch_page(
            profile_dir, headless=headless, slow_mo=slow_mo
        )
        self.env = Browser(page=page, max_obs_tokens=budget, block_resources=block_resources)
        page.goto(start_url, wait_until="domcontentloaded")

    def close(self) -> None:
        self.env.close()
        try:
            self._context.close()
        except Exception:
            pass
        try:
            self._playwright.stop()
        except Exception:
            pass

    def chat(self, user_text: str) -> str:
        try:
            observation = self.env.observe(mode="full").text
        except Exception as exc:
            observation = f"error: {exc}"
        self.messages.append(
            {"role": "user", "content": f"{user_text}\n\nCurrent browser state:\n{observation}"}
        )
        reply = self._run_loop()
        self._trim_history()
        return reply

    def resume(self) -> str:
        return self.chat("Continue from where you left off and finish the current task.")

    def _emit(self, kind: str, **data: Any) -> None:
        if self.on_event is not None:
            self.on_event(kind, data)

    def _nudge(self, reason: str, content: str) -> None:
        self._emit("nudge", reason=reason)
        self.messages.append({"role": "user", "content": content})

    def _read(self, arguments: str) -> str:
        try:
            args = json.loads(arguments or "{}")
        except ValueError:
            args = {}
        try:
            raw = page_text(self.env.page)
        except Exception as exc:
            return f"error: {exc}"
        return read_page(raw, query=args.get("query"), page=int(args.get("page") or 0))

    def _load_skill(self, arguments: str) -> str:
        try:
            args = json.loads(arguments or "{}")
        except ValueError:
            args = {}
        name = str(args.get("name") or "")
        spec = SKILLS.get(name)
        if spec is None:
            return f"error: unknown skill {name!r}; available: {', '.join(SKILLS)}"
        for tool in spec["tools"]:
            if tool not in self.tools:
                self.tools.append(tool)
        self.skill_handlers.update(spec["handlers"])
        self._emit("skill", name=name)
        return spec["instructions"]

    def _call_skill(self, name: str, arguments: str) -> str:
        try:
            args = json.loads(arguments or "{}")
        except ValueError:
            return "error: tool arguments were not valid JSON; retry with fewer elements"
        try:
            return self.skill_handlers[name](self, args)
        except Exception as exc:
            return f"error: {exc}"

    def _run_loop(self) -> str:
        active_model = self.model
        failures = 0
        nudges = 0
        api_errors = 0
        recent = deque(maxlen=6)

        for _ in range(self.max_steps):
            self._emit("thinking_start", model=active_model)
            response = self.env.while_thinking(
                self.client.chat.completions.create,
                model=active_model,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                tools=self.tools,
                messages=self.messages,
            )
            self._emit("thinking_end")
            if not getattr(response, "choices", None):
                api_errors += 1
                detail = str(getattr(response, "error", None) or "no choices in response")
                if api_errors >= 3:
                    return f"stopped: the model API kept failing ({detail})"
                self._emit("api_retry", detail=detail)
                sleep(2 * api_errors)
                continue
            api_errors = 0
            message = response.choices[0].message
            self.messages.append(message)

            if not message.tool_calls:
                content = (message.content or "").strip()
                if not content and nudges < 2:
                    nudges += 1
                    self._nudge("empty reply", EMPTY_REPLY_RETRY)
                    continue
                if leaks_tool_call(content) and nudges < 2:
                    nudges += 1
                    self._nudge("tool call leaked as text", LEAKED_TOOL_CALL_RETRY)
                    continue
                if asks_user_to_decide(content) and nudges < 2:
                    nudges += 1
                    self._nudge("asked user to decide", QUESTION_REPLY_RETRY)
                    continue
                return content

            blocked = False
            for tool_call in message.tool_calls:
                name = tool_call.function.name
                arguments = tool_call.function.arguments or ""
                self._emit("tool_start", name=name, arguments=arguments)
                if name == "read":
                    result = self._read(arguments)
                elif name == "skill":
                    result = self._load_skill(arguments)
                elif name in self.skill_handlers:
                    result = self._call_skill(name, arguments)
                else:
                    result = dispatch(self.env, tool_call)
                signature = act_signature(name, arguments)
                repeats = sum(1 for item in recent if item == signature)
                recent.append(signature)
                if repeats >= 1:
                    result = f"{result}\n{REPEAT_WARNING}"
                failed = is_failure(result) or repeats >= 2
                self._emit("tool_end", name=name, result=result, ok=not failed)
                self.messages.append({"role": "tool", "tool_call_id": tool_call.id, "content": result})
                failures = failures + 1 if failed else 0
                if failures >= self.escalate_after and active_model != self.escalation_model:
                    active_model = self.escalation_model
                    self._emit("escalate", model=active_model)
                if looks_blocked(result):
                    blocked = True
            if blocked:
                return BLOCKED_HANDOFF

        return "stopped: max steps reached"

    def _trim_history(self) -> None:
        if len(self.messages) <= self.history_limit:
            return
        cut = len(self.messages) - self.history_limit
        while cut < len(self.messages):
            entry = self.messages[cut]
            if isinstance(entry, dict) and entry.get("role") == "user":
                break
            cut += 1
        self.messages = [self.messages[0]] + self.messages[cut:]
