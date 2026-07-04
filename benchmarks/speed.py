from __future__ import annotations

import argparse
from statistics import median
from time import perf_counter
from urllib.parse import quote

from ocu import Browser

PAGE_TEMPLATE = """<!doctype html><html><body>
<input id="q" placeholder="Search products">
<button id="go" onclick="document.getElementById('status').textContent='Searched: '+document.getElementById('q').value">Search</button>
<p id="status">Ready</p>
{rows}
</body></html>"""


def build_page(rows: int) -> str:
    body = "\n".join(
        f'<div><span>Product {index}</span>'
        f'<button onclick="this.textContent=\'Added {index}\'">Add {index}</button></div>'
        for index in range(rows)
    )
    return "data:text/html," + quote(PAGE_TEMPLATE.format(rows=body))


def timed(fn, runs: int) -> list[float]:
    samples = []
    for _ in range(runs):
        start = perf_counter()
        fn()
        samples.append((perf_counter() - start) * 1000)
    return samples


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", type=int, default=150)
    parser.add_argument("--runs", type=int, default=20)
    parser.add_argument("--settle-ms", type=int, default=200)
    parser.add_argument("--ax", action="store_true")
    args = parser.parse_args()

    env = Browser(
        start_url=build_page(args.rows),
        max_obs_tokens=1500,
        headless=True,
        include_ax=args.ax,
        settle_ms=args.settle_ms,
    )
    try:
        first = env.observe(mode="full")
        go_id = next(e.id for e in first.elements.values() if e.text == "Search")
        q_id = next(e.id for e in first.elements.values() if e.role == "input")

        observe_ms = timed(lambda: env.observe(mode="full"), args.runs)
        act_ms = timed(lambda: env.act("click", target=go_id), args.runs)
        batch = [
            {"verb": "click", "target": q_id},
            {"verb": "type", "target": q_id, "text": "wireless mouse"},
            {"verb": "click", "target": go_id},
        ]
        batch_ms = timed(lambda: env.act_batch(batch), args.runs)

        print(f"page elements: {len(first.elements)}  obs tokens: {first.tokens}")
        print(f"observe full   p50 {median(observe_ms):7.1f} ms  min {min(observe_ms):7.1f} ms")
        print(f"act single     p50 {median(act_ms):7.1f} ms  min {min(act_ms):7.1f} ms")
        print(f"act batch x3   p50 {median(batch_ms):7.1f} ms  min {min(batch_ms):7.1f} ms")
        print(f"batch per-step p50 {median(batch_ms) / 3:7.1f} ms")
    finally:
        env.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
