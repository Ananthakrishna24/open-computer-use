from __future__ import annotations

from ocu import Browser
from ocu.integrations.openrouter import DEFAULT_MODEL, TOOLS, create_client, dispatch

SYSTEM_PROMPT = (
    "You control a real browser through two tools: observe and act. "
    "Target elements by their [id]. Batch predictable steps into one act call, "
    "for example click, type, then press Enter. Call observe full only when lost. "
    "When the task is complete, answer in plain text without calling tools."
)


def run(url: str, task: str, *, model: str = DEFAULT_MODEL, budget: int = 1200, max_steps: int = 40) -> str:
    client = create_client()
    env = Browser(start_url=url, max_obs_tokens=budget)
    try:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Task: {task}\n\n{env.observe().text}"},
        ]
        for _ in range(max_steps):
            response = client.chat.completions.create(
                model=model,
                max_tokens=400,
                tools=TOOLS,
                messages=messages,
            )
            message = response.choices[0].message
            messages.append(message)
            if not message.tool_calls:
                return message.content or ""
            for tool_call in message.tool_calls:
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": dispatch(env, tool_call),
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
    args = parser.parse_args()
    print(run(args.url, args.task, model=args.model))
