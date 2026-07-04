from __future__ import annotations

import argparse
import base64
import json
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from ocu import Browser
from ocu.integrations.openrouter import DEFAULT_MODEL, TOOLS, create_client, dispatch
from runner import Result, summarize, to_markdown

PRICES_PER_M = {
    "google/gemma-4-26b-a4b-it": (0.06, 0.33),
    "google/gemma-4-31b-it": (0.12, 0.35),
}

TASKS = [
    {
        "id": "books-price",
        "url": "https://books.toscrape.com",
        "task": "Find the book 'Sharp Objects' and report its price.",
        "expect": ["47.82"],
    },
    {
        "id": "books-travel-count",
        "url": "https://books.toscrape.com",
        "task": "Open the Travel category and report how many results it lists.",
        "expect": ["11"],
    },
    {
        "id": "books-stock",
        "url": "https://books.toscrape.com",
        "task": "Open the product page for 'A Light in the Attic' and report its availability.",
        "expect": ["in stock"],
    },
    {
        "id": "quotes-author",
        "url": "https://quotes.toscrape.com",
        "task": "Report the author of the first quote on the page.",
        "expect": ["einstein"],
    },
    {
        "id": "quotes-login-page",
        "url": "https://quotes.toscrape.com",
        "task": "Open the Login page and report the labels of the two form fields.",
        "expect": ["username", "password"],
    },
    {
        "id": "wiki-turing",
        "url": "https://en.wikipedia.org/wiki/Alan_Turing",
        "task": "Report the year Alan Turing was born.",
        "expect": ["1912"],
    },
    {
        "id": "wiki-python-creator",
        "url": "https://en.wikipedia.org",
        "task": "Find who created the Python programming language and report the surname.",
        "expect": ["rossum"],
    },
    {
        "id": "example-learn-more",
        "url": "https://example.com",
        "task": "Open the 'Learn more' link and report the domain of the page you land on.",
        "expect": ["iana.org"],
    },
    {
        "id": "github-cpython",
        "url": "https://github.com/python/cpython",
        "task": "Report the description of this repository.",
        "expect": ["programming language"],
    },
]

EMPTY_REPLY_RETRY = (
    "You returned an empty answer. Continue the task: use tools if more browser "
    "work is needed, otherwise state the final answer with the requested fact."
)

OCU_SYSTEM_PROMPT = (
    "You control a real browser through two tools: observe and act. "
    "Target elements by their [id]. Batch predictable steps into one act call. "
    "The goto verb opens any URL given in text. To read content-heavy pages call "
    "observe with mode text. Never ask the user questions; keep acting until the "
    "task is done, then answer in plain text without calling tools, quoting the "
    "requested fact exactly as seen on the page."
)

SCREENSHOT_SYSTEM_PROMPT = (
    "You control a real browser. Each user message contains a screenshot of the "
    "current page; the viewport is 1280x720. Use the act tool with pixel "
    "coordinates read from the screenshot: click, type (text goes to the focused "
    "element), press (key name in text), scroll (dy in pixels), goto (URL in "
    "text), drag (coordinate to to). After each act you get a fresh screenshot. "
    "Never ask the user questions; keep acting until the task is done, then "
    "answer in plain text without calling tools, quoting the requested fact "
    "exactly as seen on the page."
)

SCREENSHOT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "act",
            "description": "Execute one or more actions grounded in screenshot pixel coordinates.",
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
                                    "enum": ["click", "type", "press", "scroll", "drag", "wait", "goto", "back"],
                                },
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
                                },
                                "text": {"type": ["string", "null"]},
                            },
                            "required": ["verb"],
                            "additionalProperties": True,
                        },
                    }
                },
                "required": ["actions"],
                "additionalProperties": False,
            },
        },
    }
]


class UsageMeter:
    def __init__(self) -> None:
        self.input_tokens = 0
        self.output_tokens = 0
        self.steps = 0

    def add(self, response) -> None:
        self.steps += 1
        usage = getattr(response, "usage", None)
        if usage is not None:
            self.input_tokens += int(getattr(usage, "prompt_tokens", 0) or 0)
            self.output_tokens += int(getattr(usage, "completion_tokens", 0) or 0)


def _completion(client, model, messages, tools, meter):
    response = client.chat.completions.create(
        model=model,
        max_tokens=500,
        temperature=0.2,
        tools=tools,
        messages=messages,
    )
    meter.add(response)
    if not getattr(response, "choices", None):
        raise RuntimeError(f"no choices in response: {getattr(response, 'error', None)}")
    return response.choices[0].message


def _compact_observations(messages):
    latest = max(
        (i for i, m in enumerate(messages) if isinstance(m, dict) and m.get("role") == "tool"),
        default=None,
    )
    for i, entry in enumerate(messages):
        if i == latest or not isinstance(entry, dict) or entry.get("role") != "tool":
            continue
        content = entry.get("content") or ""
        if content.startswith("## screen") or content.startswith("## page text"):
            did = next((l for l in content.splitlines() if l.startswith("did:")), "")
            entry["content"] = f"{did}\n(older observation removed)".strip()


VERBOSE = False


def run_ocu(client, model, url, task, max_steps, meter):
    env = Browser(start_url=url, headless=True, max_obs_tokens=1200)
    try:
        messages = [
            {"role": "system", "content": OCU_SYSTEM_PROMPT},
            {"role": "user", "content": f"Task: {task}\n\n{env.observe().text}"},
        ]
        nudges = 0
        for _ in range(max_steps):
            message = _completion(client, model, messages, TOOLS, meter)
            messages.append(message)
            if not message.tool_calls:
                content = (message.content or "").strip()
                if not content and nudges < 2:
                    nudges += 1
                    messages.append({"role": "user", "content": EMPTY_REPLY_RETRY})
                    continue
                return content
            for tool_call in message.tool_calls:
                result = dispatch(env, tool_call)
                if VERBOSE:
                    print(f">>> {tool_call.function.name} {tool_call.function.arguments}\n{result}\n", flush=True)
                messages.append({"role": "tool", "tool_call_id": tool_call.id, "content": result})
            _compact_observations(messages)
        return "stopped: max steps reached"
    finally:
        env.close()


def _did_line(text: str) -> str:
    for line in text.splitlines():
        if line.startswith("did:") or line.startswith("error:"):
            return line
    return text.splitlines()[0] if text else "ok"


def _screenshot_message(env, note):
    image = base64.b64encode(env.screenshot()).decode()
    return {
        "role": "user",
        "content": [
            {"type": "text", "text": note},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image}"}},
        ],
    }


def run_screenshot(client, model, url, task, max_steps, meter):
    env = Browser(start_url=url, headless=True)
    try:
        messages = [
            {"role": "system", "content": SCREENSHOT_SYSTEM_PROMPT},
            _screenshot_message(env, f"Task: {task}\n\nCurrent page screenshot:"),
        ]
        nudges = 0
        for _ in range(max_steps):
            message = _completion(client, model, messages, SCREENSHOT_TOOLS, meter)
            messages.append(message)
            if not message.tool_calls:
                content = (message.content or "").strip()
                if not content and nudges < 2:
                    nudges += 1
                    messages.append({"role": "user", "content": EMPTY_REPLY_RETRY})
                    continue
                return content
            for tool_call in message.tool_calls:
                try:
                    payload = json.loads(tool_call.function.arguments or "{}")
                    result = _did_line(env.act_batch(payload.get("actions", []), guard="none").text)
                except Exception as exc:
                    result = f"error: {exc}"
                messages.append({"role": "tool", "tool_call_id": tool_call.id, "content": result})
            for entry in messages:
                if isinstance(entry, dict) and entry.get("role") == "user" and isinstance(entry.get("content"), list):
                    entry["content"] = "(older screenshot removed)"
            messages.append(_screenshot_message(env, "Current page screenshot:"))
        return "stopped: max steps reached"
    finally:
        env.close()


def cost_usd(model, input_tokens, output_tokens):
    price_in, price_out = PRICES_PER_M.get(model, (0.0, 0.0))
    return (input_tokens * price_in + output_tokens * price_out) / 1_000_000


def grade(answer, expect):
    lowered = (answer or "").casefold()
    return all(marker.casefold() in lowered for marker in expect)


def run_suite(systems, model, max_steps, task_filter):
    client = create_client()
    runners = {"ocu": run_ocu, "screenshot": run_screenshot}
    results = []
    for spec in TASKS:
        if task_filter and spec["id"] not in task_filter:
            continue
        for system in systems:
            meter = UsageMeter()
            try:
                answer = runners[system](client, model, spec["url"], spec["task"], max_steps, meter)
            except Exception as exc:
                answer = f"error: {exc}"
            success = grade(answer, spec["expect"])
            results.append(
                Result(
                    suite="webvoyager-subset",
                    system=system,
                    model=model,
                    task=spec["id"],
                    input_tokens=meter.input_tokens,
                    output_tokens=meter.output_tokens,
                    steps=meter.steps,
                    cost_usd=cost_usd(model, meter.input_tokens, meter.output_tokens),
                    success=success,
                )
            )
            print(
                f"[{spec['id']}] {system}: success={success} steps={meter.steps} "
                f"tokens={meter.input_tokens}+{meter.output_tokens} answer={answer[:120]!r}",
                flush=True,
            )
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--systems", default="ocu,screenshot")
    parser.add_argument("--tasks", default="")
    parser.add_argument("--max-steps", type=int, default=15)
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--out", type=Path, default=Path("benchmarks/webvoyager_results.json"))
    parser.add_argument("--table", type=Path, default=Path("benchmarks/results.md"))
    args = parser.parse_args()

    global VERBOSE
    VERBOSE = args.verbose
    systems = [s.strip() for s in args.systems.split(",") if s.strip()]
    task_filter = {t.strip() for t in args.tasks.split(",") if t.strip()}
    results = run_suite(systems, args.model, args.max_steps, task_filter)

    existing = []
    if args.out.exists():
        existing = [Result(**row) for row in json.loads(args.out.read_text())]
        replaced = {(r.system, r.model, r.task) for r in results}
        existing = [r for r in existing if (r.system, r.model, r.task) not in replaced]
    merged = existing + results
    args.out.write_text(json.dumps([asdict(r) for r in merged], indent=2))
    table = to_markdown(summarize(merged))
    args.table.write_text(table)
    print()
    print(table)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
