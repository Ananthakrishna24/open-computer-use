from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Any


@dataclass(frozen=True, slots=True)
class Result:
    suite: str
    system: str
    model: str
    task: str
    input_tokens: int
    output_tokens: int
    steps: int
    cost_usd: float
    success: bool

    @property
    def tokens_per_step(self) -> float:
        if self.steps <= 0:
            return 0.0
        return (self.input_tokens + self.output_tokens) / self.steps


def load_results(path: Path) -> list[Result]:
    rows = json.loads(path.read_text())
    return [Result(**row) for row in rows]


def summarize(results: list[Result]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str], list[Result]] = {}
    for result in results:
        groups.setdefault((result.suite, result.system, result.model), []).append(result)

    summaries = []
    for (suite, system, model), rows in sorted(groups.items()):
        successes = sum(1 for row in rows if row.success)
        total_cost = sum(row.cost_usd for row in rows)
        summaries.append(
            {
                "suite": suite,
                "system": system,
                "model": model,
                "tasks": len(rows),
                "tokens_per_step": mean(row.tokens_per_step for row in rows),
                "tokens_per_task": mean(row.input_tokens + row.output_tokens for row in rows),
                "cost_per_task": mean(row.cost_usd for row in rows),
                "success_rate": 100 * successes / len(rows),
                "cost_per_success": total_cost / successes if successes else float("inf"),
            }
        )
    return summaries


def to_markdown(summaries: list[dict[str, Any]]) -> str:
    lines = [
        "# Benchmark Results",
        "",
        "| Suite | System | Model | Tasks | tokens/step | tokens/task | $/task | success % | $/success |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in summaries:
        per_success = row["cost_per_success"]
        lines.append(
            "| {suite} | {system} | {model} | {tasks} | {tokens_per_step:.1f} | "
            "{tokens_per_task:.0f} | {cost_per_task:.4f} | {success_rate:.1f} | {ps} |".format(
                ps="—" if per_success == float("inf") else f"{per_success:.4f}", **row
            )
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("results_json", type=Path)
    parser.add_argument("--out", type=Path, default=Path("benchmarks/results.md"))
    args = parser.parse_args()
    args.out.write_text(to_markdown(summarize(load_results(args.results_json))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
