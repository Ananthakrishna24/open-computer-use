from __future__ import annotations

import argparse

from .core import DEFAULT_MODEL, DEFAULT_PROFILE, ESCALATION_MODEL, Agent


def main() -> None:
    parser = argparse.ArgumentParser(description="Production browser agent for small models.")
    parser.add_argument("url", nargs="?", default="https://www.bing.com")
    parser.add_argument("task", nargs="?")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--escalation-model", default=ESCALATION_MODEL)
    parser.add_argument("--budget", type=int, default=1800)
    parser.add_argument("--max-steps", type=int, default=40)
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--profile", default=str(DEFAULT_PROFILE))
    parser.add_argument("--block-resources", action="store_true")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    agent = Agent(
        args.url,
        model=args.model,
        escalation_model=args.escalation_model,
        budget=args.budget,
        max_steps=args.max_steps,
        headless=args.headless,
        profile_dir=args.profile,
        block_resources=args.block_resources,
        verbose=args.verbose,
    )
    try:
        if args.task:
            print(agent.chat(args.task))
            if args.once:
                return
        print("Agent ready. Type a task; resume continues after a manual step; /quit exits.")
        while True:
            try:
                task = input("you> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                return
            if not task:
                continue
            lowered = task.lower()
            if lowered in {"/quit", "/exit", "quit", "exit"}:
                return
            if lowered in {"resume", "/resume", "done", "continue"}:
                print(agent.resume())
                continue
            print(agent.chat(task))
    finally:
        agent.close()


if __name__ == "__main__":
    main()
