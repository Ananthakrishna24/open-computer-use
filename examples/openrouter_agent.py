from __future__ import annotations

from ocu import Browser
from ocu.integrations.openrouter import (
    DEFAULT_MODEL,
    ESCALATION_MODEL,
    TOOLS,
    create_client,
    dispatch,
)

SYSTEM_PROMPT = (
    "You control a real browser through two tools: observe and act. "
    "Target elements by their [id]. Batch predictable steps into one act call, "
    "for example click, type, then press Enter. Call observe full only when lost. "
    "When the task is complete, answer in plain text without calling tools."
)


def _is_failure(result: str) -> bool:
    return result.startswith("error:") or "aborted at step" in result


def run(
    url: str,
    task: str,
    *,
    model: str = DEFAULT_MODEL,
    escalation_model: str = ESCALATION_MODEL,
    escalate_after: int = 2,
    budget: int = 1200,
    max_steps: int = 40,
) -> str:
    client = create_client()
    env = Browser(start_url=url, max_obs_tokens=budget)
    active_model = model
    failures = 0
    try:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Task: {task}\n\n{env.observe().text}"},
        ]
        for _ in range(max_steps):
            response = client.chat.completions.create(
                model=active_model,
                max_tokens=400,
                tools=TOOLS,
                messages=messages,
            )
            message = response.choices[0].message
            messages.append(message)
            if not message.tool_calls:
                return message.content or ""
            for tool_call in message.tool_calls:
                result = dispatch(env, tool_call)
                failures = failures + 1 if _is_failure(result) else 0
                if failures >= escalate_after:
                    active_model = escalation_model
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": result,
                    }
                )
        return "stopped: max steps reached"
    finally:
        env.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("url")
    parser.add_argument("task")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--escalation-model", default=ESCALATION_MODEL)
    args = parser.parse_args()
    print(run(args.url, args.task, model=args.model, escalation_model=args.escalation_model))
