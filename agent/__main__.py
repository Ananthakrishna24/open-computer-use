from __future__ import annotations

import argparse
import contextlib

with contextlib.suppress(ImportError):
    import readline

from .browser import DEFAULT_PROFILE
from .core import DEFAULT_MODEL, ESCALATION_MODEL, Agent
from .ui import UI


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

    ui = UI(verbose=args.verbose)
    agent = Agent(
        args.url,
        model=args.model,
        escalation_model=args.escalation_model,
        budget=args.budget,
        max_steps=args.max_steps,
        headless=args.headless,
        profile_dir=args.profile,
        block_resources=args.block_resources,
        on_event=ui.event,
    )
    try:
        if args.task:
            ui.begin_turn()
            ui.say(agent.chat(args.task))
            if args.once:
                return
        ui.banner(agent.model)
        while True:
            try:
                task = ui.ask().strip()
            except (EOFError, KeyboardInterrupt):
                print()
                return
            if not task:
                continue
            lowered = task.lower()
            if lowered in {"/quit", "/exit", "quit", "exit"}:
                return
            if lowered in {"/help", "help", "?"}:
                ui.help()
                continue
            ui.begin_turn()
            try:
                if lowered in {"resume", "/resume", "done", "continue"}:
                    ui.say(agent.resume())
                else:
                    ui.say(agent.chat(task))
            except KeyboardInterrupt:
                ui.interrupted()
    finally:
        agent.close()


if __name__ == "__main__":
    main()
