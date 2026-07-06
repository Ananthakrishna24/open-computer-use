from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ocu.env import Desktop
from ocu.integrations.openrouter import TOOLS, create_client, dispatch

DESKTOP_MODEL = "google/gemma-4-31b-it"

LOOK_TOOL = {
    "type": "function",
    "function": {
        "name": "look",
        "description": (
            "Attach a screenshot of the current screen to the conversation so you can "
            "see it yourself. Use it whenever text observations cannot answer: images, "
            "icons, visual layout, or to verify what you changed."
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

DESKTOP_TOOLS = TOOLS + [LOOK_TOOL]

SYSTEM_PROMPT = (
    "You control a real Linux desktop through two tools: observe and act. "
    "Observations list on-screen widgets from the accessibility tree; target them by "
    "their [id] in the field named target. Batch predictable steps into one act call, "
    "at most 8 distinct actions. Typing replaces whatever the focused field contains. "
    "There is no goto or back verb on the desktop: open and switch apps with clicks "
    "and keyboard shortcuts via press (for example Super, Alt+Tab, Ctrl+T, Enter). "
    "If a widget you need is missing from the observation, use look to see the screen "
    "and fall back to coordinate clicks. Verify visual results with look before "
    "answering. Never ask the user questions; keep acting until the task is done, "
    "then answer in plain text without calling tools."
)

EMPTY_REPLY_RETRY = (
    "You returned an empty answer. Continue the task: use tools if more desktop work "
    "is needed, otherwise state the final result."
)


class DesktopAgent:
    def __init__(
        self,
        *,
        model: str = DESKTOP_MODEL,
        budget: int = 2500,
        max_steps: int = 40,
        max_tokens: int = 1000,
        temperature: float = 0.2,
        verbose: bool = False,
    ) -> None:
        self.client = create_client()
        self.model = model
        self.max_steps = max_steps
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.verbose = verbose
        self.env = Desktop(max_obs_tokens=budget)
        self.messages: list = [{"role": "system", "content": SYSTEM_PROMPT}]

    def chat(self, task: str) -> str:
        try:
            observation = self.env.observe(mode="full").text
        except Exception as exc:
            observation = f"error: {exc}"
        self.messages.append(
            {"role": "user", "content": f"{task}\n\nCurrent screen state:\n{observation}"}
        )
        nudges = 0
        for _ in range(self.max_steps):
            response = self.client.chat.completions.create(
                model=self.model,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                tools=DESKTOP_TOOLS,
                messages=self.messages,
            )
            if not getattr(response, "choices", None):
                return f"stopped: model API failed ({getattr(response, 'error', None)})"
            message = response.choices[0].message
            self.messages.append(message)
            if not message.tool_calls:
                content = (message.content or "").strip()
                if not content and nudges < 2:
                    nudges += 1
                    self.messages.append({"role": "user", "content": EMPTY_REPLY_RETRY})
                    continue
                return content
            look_question = None
            for tool_call in message.tool_calls:
                if tool_call.function.name == "look":
                    try:
                        args = json.loads(tool_call.function.arguments or "{}")
                    except ValueError:
                        args = {}
                    look_question = args.get("question") or "Describe what is on screen."
                    result = "screenshot attached in the next message"
                else:
                    result = dispatch(self.env, tool_call)
                if self.verbose:
                    print(f">>> {tool_call.function.name} {tool_call.function.arguments}\n{result}\n")
                self.messages.append(
                    {"role": "tool", "tool_call_id": tool_call.id, "content": result}
                )
            if look_question is not None:
                self._attach_screenshot(look_question)
        return "stopped: max steps reached"

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
                    {"type": "text", "text": f"Screenshot of the current screen. {question}"},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image}"}},
                ],
            }
        )


def run_repl(agent: DesktopAgent, first_task: str | None = None, once: bool = False) -> None:
    if first_task:
        print(agent.chat(first_task))
        if once:
            return
    print("Desktop agent is live. Chat freely; /observe, /quit.")
    while True:
        try:
            task = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not task:
            continue
        if task.lower() in {"/quit", "/exit", "quit", "exit"}:
            return
        if task.lower().startswith("/observe"):
            print(agent.env.observe(mode="full").text)
            continue
        print(agent.chat(task))


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Conversational OpenRouter Linux desktop agent.")
    parser.add_argument("task", nargs="?")
    parser.add_argument("--model", default=DESKTOP_MODEL)
    parser.add_argument("--budget", type=int, default=2500)
    parser.add_argument("--max-steps", type=int, default=40)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    agent = DesktopAgent(
        model=args.model,
        budget=args.budget,
        max_steps=args.max_steps,
        verbose=args.verbose,
    )
    run_repl(agent, first_task=args.task, once=args.once)
