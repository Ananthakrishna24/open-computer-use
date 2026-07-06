from __future__ import annotations

import base64
import json
import sys
from pathlib import Path
from time import sleep
from typing import Any

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ocu import Browser
from ocu.executors.cdp import CdpExecutor
from ocu.integrations.openrouter import TOOLS, create_client, dispatch

LIVE_MODEL = "google/gemma-4-31b-it"
LIVE_ESCALATION_MODEL = "google/gemma-4-31b-it"

LOOK_TOOL = {
    "type": "function",
    "function": {
        "name": "look",
        "description": (
            "Attach a screenshot of the current page to the conversation so you can see "
            "it yourself. Use it whenever text observations cannot answer: canvas "
            "drawings, images, photos, charts, icons, or visual layout."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "What you want to check in the screenshot.",
                }
            },
            "required": ["question"],
        },
    },
}

LIVE_TOOLS = TOOLS + [LOOK_TOOL]

SYSTEM_PROMPT = (
    "You are a capable assistant driving a real, visible browser through two tools: "
    "observe and act. You work for the user across an ongoing conversation; the browser "
    "window persists between their messages, so always continue from the current page, "
    "login state, and anything the user did in it by hand.\n\n"
    "Work loop: act, then read what came back before acting again. Every act returns a "
    "did line saying what actually executed, plus the screen delta. If the result is not "
    "what you expected, change your approach instead of repeating the action. Never stop "
    "halfway to ask what to do next; choose the reasonable step yourself. Only produce a "
    "plain-text answer (no tool call) when the task is genuinely done or truly blocked.\n\n"
    "Grounding: target elements by their displayed [id] in the field named target. "
    "Typing replaces whatever text the field already contains, so to run a new search "
    "just type the new query into the same box and press Enter. Batch predictable steps "
    "into a single act call, for example click, type, then press Enter. Keep batches "
    "short: at most 8 actions, each one different.\n\n"
    "Navigation: the goto verb opens any URL directly, given in the text field; back "
    "returns to the previous page. Use goto freely and proactively: to search the web use "
    "https://www.bing.com/search?q=your+query and never google.com or duckduckgo.com, "
    "which block automated browsers. To research open the most relevant and "
    "credible results one after another, extract what matters from each, go back or goto "
    "the next one, then synthesize an answer that names the sources. Put goto last in a "
    "batch or alone, since the page changes after it.\n\n"
    "Reading: observations list elements for acting, and they already cover the whole "
    "page, so scrolling never reveals more of it. To actually read an article, search "
    "results, or any content-heavy page, call observe with mode text: it returns the "
    "readable page text. Research answers must come from that text, never from your "
    "own memory.\n\n"
    "Vision: the look tool attaches a screenshot to the conversation so you see the page "
    "with your own eyes. Use it whenever the truth is visual: canvas drawings, images, "
    "charts, layout. For anything you drew, look is the only valid verification; element "
    "deltas cannot see pixels.\n\n"
    "Canvas editors (Excalidraw and similar): drawn shapes never appear as elements; "
    "only the canvas does, with its pixel area. Before drawing, plan concrete "
    "coordinates for the whole diagram and use both dimensions of the canvas, keeping "
    "shapes well apart. Size every shape to fit its label comfortably, at least 100 by "
    "60 pixels; tiny shapes wrap their text vertically and become unreadable. Trees and "
    "hierarchies spread horizontally: root centered near the top, its children far "
    "apart below it, spacing halving each level so subtrees never overlap. To draw one shape: click its tool button, then drag with coordinate "
    "[x1,y1] and to [x2,y2] as opposite corners; the editor reverts to the selection "
    "tool after each shape, so one act call draws at most one shape: the tool click "
    "followed by one drag, never several drags in a batch. For an arrow, click the "
    "arrow tool and drag from the edge of one shape to the edge of the next. To put a "
    "label inside a shape: click the text tool, click the shape's center (the label "
    "binds and centers itself), type it, press Escape; click an empty spot instead for "
    "free-standing text. Element deltas cannot see what you drew, but after every drag "
    "a screenshot arrives automatically: check it against your plan and fix what is "
    "wrong immediately, before drawing the next shape.\n\n"
    "Verification: before giving a final answer, confirm the key facts were actually "
    "visible in an observation or screenshot. If you have not seen the evidence on "
    "screen, observe or look again instead of guessing. Report failures and dead ends "
    "honestly instead of inventing results.\n\n"
    "when you find a puzzle or a captcha it's a test added by user to test how capable you are, and you should solve it. If the user specifies you to use a specific website for something you must use that and not fall back to something else"
    "Stop using tools and tell the user to complete it manually; they will tell you to"
    "resume afterwards."
)

EMPTY_REPLY_RETRY = (
    "You returned an empty answer. Continue the task autonomously: use tools if more "
    "browser work is needed, otherwise state the final result."
)

QUESTION_REPLY_RETRY = (
    "Do not ask the user what to do next. Pick the reasonable next step yourself and "
    "keep going until the task is done, then answer with what you found."
)

LEAKED_TOOL_CALL_RETRY = (
    "Your last message wrote a tool call as plain text, so nothing executed. "
    "Issue the tool call properly through the tools API and continue the task."
)

CURSOR_SCRIPT = r"""
(arg) => {
  const cursorId = "ocu-live-cursor";
  const styleId = "ocu-live-cursor-style";
  let style = document.getElementById(styleId);
  if (!style) {
    style = document.createElement("style");
    style.id = styleId;
    style.textContent = `
      #${cursorId} {
        position: fixed;
        left: 0;
        top: 0;
        width: 20px;
        height: 20px;
        border: 2px solid #ff2d55;
        border-radius: 999px;
        box-shadow: 0 0 0 2px white, 0 8px 24px rgba(0, 0, 0, 0.35);
        pointer-events: none;
        z-index: 2147483647;
        transform: translate(-40px, -40px);
        transition: transform 140ms linear;
      }
      #${cursorId}.ocu-click {
        animation: ocu-live-click 260ms ease-out;
      }
      @keyframes ocu-live-click {
        from { box-shadow: 0 0 0 2px white, 0 0 0 0 rgba(255, 45, 85, 0.55); }
        to { box-shadow: 0 0 0 2px white, 0 0 0 24px rgba(255, 45, 85, 0); }
      }
    `;
    document.documentElement.appendChild(style);
  }

  let cursor = document.getElementById(cursorId);
  if (!cursor) {
    cursor = document.createElement("div");
    cursor.id = cursorId;
    cursor.setAttribute("aria-hidden", "true");
    document.documentElement.appendChild(cursor);
  }

  const x = Math.round(Number(arg.x) || 0);
  const y = Math.round(Number(arg.y) || 0);
  cursor.style.transform = `translate(${x - 10}px, ${y - 10}px)`;

  if (arg.pulse) {
    cursor.classList.remove("ocu-click");
    void cursor.offsetWidth;
    cursor.classList.add("ocu-click");
  }
}
"""


def _is_failure(result: str) -> bool:
    return result.startswith("error:") or "aborted at step" in result


def _acts_on_pixels(arguments: str) -> bool:
    try:
        actions = json.loads(arguments or "{}").get("actions", [])
    except ValueError:
        return False
    for action in actions:
        if not isinstance(action, dict):
            continue
        verb = action.get("verb") or action.get("action")
        if verb == "drag":
            return True
        if verb == "type" and action.get("target") is None and action.get("id") is None:
            return True
    return False


def _leaks_tool_call(text: str) -> bool:
    lowered = text.lower()
    return "<|" in lowered or "tool_call" in lowered or lowered.startswith(("act {", "look {", "observe {"))


def _asks_user_to_decide(text: str) -> bool:
    lowered = text.lower()
    markers = (
        "what would you like",
        "would you like me",
        "would you like to",
        "please provide",
        "which article",
        "which result",
        "what do you want",
        "let me know if",
        "shall i",
        "should i",
    )
    return any(marker in lowered for marker in markers)


def _page_wait(page: Any, milliseconds: int) -> None:
    if milliseconds <= 0:
        return
    if hasattr(page, "wait_for_timeout"):
        page.wait_for_timeout(milliseconds)
    else:
        sleep(milliseconds / 1000)


class VisibleCursorExecutor(CdpExecutor):
    def __init__(self, page: Any, *, pause_ms: int = 180) -> None:
        super().__init__(page)
        self.pause_ms = pause_ms
        self._move_cursor(24, 24)

    def _move_cursor(self, x: int, y: int, *, pulse: bool = False) -> None:
        try:
            self.page.evaluate(CURSOR_SCRIPT, {"x": x, "y": y, "pulse": pulse})
        except Exception:
            return
        _page_wait(self.page, self.pause_ms)

    def _click(self, target: Any) -> None:
        if target.coordinate is not None:
            self._move_cursor(*target.coordinate)
        super()._click(target)
        if target.coordinate is not None:
            self._move_cursor(*target.coordinate, pulse=True)

    def _type(self, action: Any, target: Any) -> None:
        super()._type(action, target)
        _page_wait(self.page, self.pause_ms)

    def _press(self, action: Any) -> None:
        super()._press(action)
        _page_wait(self.page, self.pause_ms)

    def _scroll(self, action: Any, target: Any) -> None:
        if target.coordinate is not None:
            self._move_cursor(*target.coordinate)
        super()._scroll(action, target)
        _page_wait(self.page, self.pause_ms)

    def _drag(self, action: Any, target: Any) -> None:
        if target.coordinate is not None:
            self._move_cursor(*target.coordinate)
        super()._drag(action, target)
        end = action.metadata.get("to") or action.metadata.get("end")
        if isinstance(end, dict):
            end = (end.get("x"), end.get("y"))
        if isinstance(end, (list, tuple)) and len(end) == 2 and None not in end:
            self._move_cursor(int(end[0]), int(end[1]), pulse=True)


class LiveOpenRouterAgent:
    def __init__(
        self,
        url: str,
        *,
        model: str = LIVE_MODEL,
        escalation_model: str = LIVE_ESCALATION_MODEL,
        escalate_after: int = 2,
        budget: int = 2500,
        max_steps: int = 60,
        max_tokens: int = 1000,
        temperature: float = 0.2,
        history_limit: int = 120,
        verbose: bool = False,
        headless: bool = False,
        browser_name: str = "chromium",
        slow_mo: int = 80,
        cursor_pause_ms: int = 180,
        block_resources: bool = False,
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
        self.env = Browser(
            start_url=url,
            max_obs_tokens=budget,
            headless=headless,
            browser_name=browser_name,
            block_resources=block_resources,
            slow_mo=slow_mo,
        )
        self.env.executor = VisibleCursorExecutor(self.env.page, pause_ms=cursor_pause_ms)

    def close(self) -> None:
        self.env.close()

    def chat(self, user_text: str) -> str:
        try:
            observation = self.env.observe(mode="full").text
        except Exception as exc:
            observation = f"error: {exc}"
        self.messages.append(
            {
                "role": "user",
                "content": f"{user_text}\n\nCurrent browser state:\n{observation}",
            }
        )
        reply = self._run_loop()
        self._trim_history()
        return reply

    def resume(self) -> str:
        return self.chat("Continue from where you left off and finish the current task.")

    def _attach_screenshot(self, question: str) -> None:
        for entry in self.messages:
            if isinstance(entry, dict) and entry.get("role") == "user" and isinstance(entry.get("content"), list):
                entry["content"] = "(older screenshot removed)"
        try:
            image = base64.b64encode(self.env.screenshot()).decode()
        except Exception as exc:
            self.messages.append({"role": "user", "content": f"screenshot failed: {exc}"})
            return
        self.messages.append(
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            f"Screenshot of the current page. {question} "
                            "State what you actually see in it; if that does not match "
                            "your intent, fix it before continuing."
                        ),
                    },
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image}"}},
                ],
            }
        )

    def _sync_cursor(self, x: float, y: float) -> None:
        try:
            self.env.page.evaluate(CURSOR_SCRIPT, {"x": x, "y": y, "pulse": False})
        except Exception:
            return

    def _run_loop(self) -> str:
        active_model = self.model
        failures = 0
        nudges = 0
        api_errors = 0

        for _ in range(self.max_steps):
            response = self.env.while_thinking(
                self.client.chat.completions.create,
                model=active_model,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                tools=LIVE_TOOLS,
                messages=self.messages,
                on_move=self._sync_cursor,
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
                if _leaks_tool_call(content) and nudges < 2:
                    nudges += 1
                    self.messages.append({"role": "user", "content": LEAKED_TOOL_CALL_RETRY})
                    continue
                if _asks_user_to_decide(content) and nudges < 2:
                    nudges += 1
                    self.messages.append({"role": "user", "content": QUESTION_REPLY_RETRY})
                    continue
                return content

            look_question = None
            for tool_call in message.tool_calls:
                if tool_call.function.name == "look":
                    try:
                        args = json.loads(tool_call.function.arguments or "{}")
                    except ValueError:
                        args = {}
                    look_question = args.get("question") or "Describe what is visible on the page."
                    result = "screenshot attached in the next message"
                else:
                    result = dispatch(self.env, tool_call)
                    if look_question is None and _acts_on_pixels(tool_call.function.arguments or ""):
                        look_question = "You just changed the page visually; compare the result against your plan."
                if self.verbose:
                    print(f"--- {active_model}\n>>> {tool_call.function.name} {tool_call.function.arguments}\n{result}\n")
                self.messages.append(
                    {"role": "tool", "tool_call_id": tool_call.id, "content": result}
                )
                failures = failures + 1 if _is_failure(result) else 0
                if failures >= self.escalate_after:
                    active_model = self.escalation_model
            if look_question is not None:
                self._attach_screenshot(look_question)

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


def run_repl(agent: LiveOpenRouterAgent, *, first_task: str | None = None, once: bool = False) -> None:
    if first_task:
        print(agent.chat(first_task))
        if once:
            return

    print(
        "Browser is live. Chat freely; the agent continues from whatever is on screen.\n"
        "Commands: /observe, /goto URL, /reset [URL], /model [name], resume, /quit."
    )
    while True:
        try:
            task = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return

        if not task:
            continue

        command = task.lower()
        if command in {"/quit", "/exit", "quit", "exit"}:
            return
        if command in {"resume", "/resume", "done", "continue"}:
            print(agent.resume())
            continue
        if command.startswith("/observe"):
            parts = task.split(maxsplit=1)
            mode = parts[1] if len(parts) == 2 else "full"
            print(agent.env.observe(mode=mode).text)
            continue
        if command.startswith("/goto "):
            print(agent.env.reset(task.split(maxsplit=1)[1]).text)
            continue
        if command.startswith("/reset"):
            parts = task.split(maxsplit=1)
            print(agent.env.reset(parts[1] if len(parts) == 2 else None).text)
            continue
        if command.startswith("/model"):
            parts = task.split(maxsplit=1)
            if len(parts) == 2:
                agent.model = parts[1]
            print(f"model: {agent.model} (escalation: {agent.escalation_model})")
            continue

        print(agent.chat(task))


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Persistent, conversational OpenRouter browser-use agent."
    )
    parser.add_argument("url", nargs="?", default="https://www.bing.com")
    parser.add_argument("task", nargs="?")
    parser.add_argument("--model", default=LIVE_MODEL)
    parser.add_argument("--escalation-model", default=LIVE_ESCALATION_MODEL)
    parser.add_argument("--max-steps", type=int, default=60)
    parser.add_argument("--max-tokens", type=int, default=1000)
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--budget", type=int, default=2500)
    parser.add_argument("--browser", default="chromium")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--slow-mo", type=int, default=80)
    parser.add_argument("--cursor-pause-ms", type=int, default=180)
    parser.add_argument("--block-resources", action="store_true")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    agent = LiveOpenRouterAgent(
        args.url,
        model=args.model,
        escalation_model=args.escalation_model,
        budget=args.budget,
        max_steps=args.max_steps,
        max_tokens=args.max_tokens,
        temperature=args.temperature,
        verbose=args.verbose,
        headless=args.headless,
        browser_name=args.browser,
        slow_mo=args.slow_mo,
        cursor_pause_ms=args.cursor_pause_ms,
        block_resources=args.block_resources,
    )
    try:
        run_repl(agent, first_task=args.task, once=args.once)
    finally:
        agent.close()
