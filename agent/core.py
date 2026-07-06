from __future__ import annotations

import json
from collections import deque
from pathlib import Path
from time import sleep
from typing import Any

from ocu import Browser
from ocu.env import TEXT_SCRIPT
from ocu.integrations.openrouter import TOOLS, create_client, dispatch, pick_model

DEFAULT_MODEL = pick_model("fast")
ESCALATION_MODEL = pick_model("balanced")
DEFAULT_PROFILE = Path.home() / ".cache" / "ocu-agent" / "profile"

READ_TOOL = {
    "type": "function",
    "function": {
        "name": "read",
        "description": (
            "Return the readable text of the current page, split into parts that fit "
            "the context. Use query to jump to the part containing a phrase, or page "
            "to step through a long page."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "page": {"type": "integer", "default": 0},
            },
            "additionalProperties": False,
        },
    },
}

AGENT_TOOLS = TOOLS + [READ_TOOL]

SYSTEM_PROMPT = (
    "You drive a real browser with three tools: act, observe, and read.\n\n"
    "Work loop: act, then read the did line and screen delta that come back before "
    "acting again. If the result is not what you expected, change approach; never "
    "repeat an action that already failed the same way.\n\n"
    "Grounding: target elements by their displayed [id] in the target field. Typing "
    "replaces whatever the field already contains. Batch predictable steps into one "
    "act call (click, type, press Enter), at most 8 actions, each one different. Put "
    "goto last in a batch, since the page changes after it.\n\n"
    "Navigation: goto opens any URL given in the text field; back returns to the "
    "previous page. To search the web use https://www.bing.com/search?q=your+query.\n\n"
    "Reading: observations list the interactive elements of the whole page, so "
    "scrolling never reveals more of them. To read content call read: query jumps "
    "straight to the part containing a phrase, page steps through long pages. "
    "Answers must come from page text you actually saw, never from memory.\n\n"
    "Verification: before answering, confirm the key facts appeared in an observation "
    "or read result. Do not ask the user what to do next; pick the reasonable step "
    "yourself. Reply in plain text only when the task is done or truly blocked.\n\n"
    "If a login form, captcha, or human check blocks you, stop and tell the user to "
    "complete it in the browser window; they will say resume."
)

EMPTY_REPLY_RETRY = (
    "You returned an empty answer. Continue the task: use tools if more browser work "
    "is needed, otherwise state the final result."
)

QUESTION_REPLY_RETRY = (
    "Do not ask the user what to do next. Pick the reasonable next step yourself and "
    "keep going until the task is done, then answer with what you found."
)

LEAKED_TOOL_CALL_RETRY = (
    "Your last message wrote a tool call as plain text, so nothing executed. Issue "
    "the tool call properly through the tools API and continue."
)

REPEAT_WARNING = (
    "warning: you already executed exactly this and the page did not give a new "
    "result. Do something different: read the page, pick another element, or goto "
    "another URL."
)

CHALLENGE_MARKERS = (
    "verify you are human",
    "verify you're human",
    "unusual traffic",
    "captcha",
    "just a moment",
    "checking your browser",
    "are you a robot",
    "attention required",
    "access denied",
)

BLOCKED_HANDOFF = (
    "blocked: the site is showing a human check or access wall. Please complete it "
    "in the browser window, then say resume."
)


def looks_blocked(observation: str) -> bool:
    lowered = observation.casefold()
    return any(marker in lowered for marker in CHALLENGE_MARKERS)


def read_page(raw: str, *, query: str | None = None, page: int = 0, chunk_chars: int = 6000) -> str:
    body = " ".join(str(raw or "").split())
    if not body:
        return "page has no readable text"
    total = (len(body) + chunk_chars - 1) // chunk_chars
    index = max(0, min(int(page), total - 1))
    if query:
        position = body.casefold().find(str(query).casefold())
        if position < 0:
            return f'"{query}" not found in page text ({total} parts)'
        index = position // chunk_chars
    start = index * chunk_chars
    header = f"## page text (part {index + 1}/{total})"
    return header + "\n" + body[start : start + chunk_chars]


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


def launch_page(
    profile_dir: str | Path = DEFAULT_PROFILE,
    *,
    headless: bool = False,
    slow_mo: int = 60,
) -> tuple[Any, Any, Any]:
    from playwright.sync_api import sync_playwright

    Path(profile_dir).mkdir(parents=True, exist_ok=True)
    playwright = sync_playwright().start()
    options = dict(
        headless=headless,
        slow_mo=slow_mo,
        viewport={"width": 1366, "height": 768},
        args=["--disable-blink-features=AutomationControlled"],
        ignore_default_args=["--enable-automation"],
    )
    try:
        context = playwright.chromium.launch_persistent_context(str(profile_dir), channel="chrome", **options)
    except Exception:
        context = playwright.chromium.launch_persistent_context(str(profile_dir), **options)
    page = context.pages[0] if context.pages else context.new_page()
    return playwright, context, page


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
        verbose: bool = False,
    ) -> None:
        self.client = create_client()
        self.model = model
        self.escalation_model = escalation_model
        self.escalate_after = escalate_after
        self.max_steps = max_steps
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.history_limit = history_limit
        self.verbose = verbose
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

    def _read(self, arguments: str) -> str:
        try:
            args = json.loads(arguments or "{}")
        except ValueError:
            args = {}
        try:
            raw = str(self.env.page.evaluate(TEXT_SCRIPT) or "")
        except Exception as exc:
            return f"error: {exc}"
        return read_page(raw, query=args.get("query"), page=int(args.get("page") or 0))

    def _run_loop(self) -> str:
        active_model = self.model
        failures = 0
        nudges = 0
        api_errors = 0
        recent = deque(maxlen=6)

        for _ in range(self.max_steps):
            response = self.env.while_thinking(
                self.client.chat.completions.create,
                model=active_model,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                tools=AGENT_TOOLS,
                messages=self.messages,
            )
            if not getattr(response, "choices", None):
                api_errors += 1
                if api_errors >= 3:
                    detail = getattr(response, "error", None) or "no choices in response"
                    return f"stopped: the model API kept failing ({detail})"
                sleep(2 * api_errors)
                continue
            api_errors = 0
            message = response.choices[0].message
            self.messages.append(message)

            if not message.tool_calls:
                content = (message.content or "").strip()
                if not content and nudges < 2:
                    nudges += 1
                    self.messages.append({"role": "user", "content": EMPTY_REPLY_RETRY})
                    continue
                if leaks_tool_call(content) and nudges < 2:
                    nudges += 1
                    self.messages.append({"role": "user", "content": LEAKED_TOOL_CALL_RETRY})
                    continue
                if asks_user_to_decide(content) and nudges < 2:
                    nudges += 1
                    self.messages.append({"role": "user", "content": QUESTION_REPLY_RETRY})
                    continue
                return content

            blocked = False
            for tool_call in message.tool_calls:
                name = tool_call.function.name
                arguments = tool_call.function.arguments or ""
                if name == "read":
                    result = self._read(arguments)
                else:
                    result = dispatch(self.env, tool_call)
                signature = act_signature(name, arguments)
                repeats = sum(1 for item in recent if item == signature)
                recent.append(signature)
                if repeats >= 1:
                    result = f"{result}\n{REPEAT_WARNING}"
                if self.verbose:
                    print(f"--- {active_model}\n>>> {name} {arguments}\n{result}\n")
                self.messages.append({"role": "tool", "tool_call_id": tool_call.id, "content": result})
                failed = is_failure(result) or repeats >= 2
                failures = failures + 1 if failed else 0
                if failures >= self.escalate_after:
                    active_model = self.escalation_model
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
