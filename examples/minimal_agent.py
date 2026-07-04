from __future__ import annotations

from anthropic import Anthropic

from ocu import Browser
from ocu.integrations.anthropic import TOOLS, dispatch


def run(url: str, task: str, *, model: str = "claude-haiku-4-5") -> str:
    client = Anthropic()
    env = Browser(start_url=url, max_obs_tokens=1500)
    try:
        messages = [{"role": "user", "content": f"Task: {task}\n\n{env.observe().text}"}]
        while True:
            response = client.messages.create(
                model=model,
                max_tokens=400,
                tools=TOOLS,
                messages=messages,
            )
            messages.append({"role": "assistant", "content": response.content})
            if response.stop_reason != "tool_use":
                return str(response.content)
            tool_results = []
            for block in response.content:
                if getattr(block, "type", None) != "tool_use":
                    continue
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": dispatch(env, block),
                    }
                )
            messages.append({"role": "user", "content": tool_results})
    finally:
        env.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("url")
    parser.add_argument("task")
    args = parser.parse_args()
    print(run(args.url, args.task))
