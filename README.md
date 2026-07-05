# open-computer-use

`open-computer-use` is a perception and action layer for computer-use agents. It is not an
agent loop, prompt library, planner, or trained model. The package gives any host harness two
tools:

- `observe` returns a token-budgeted screen observation.
- `act` executes grounded actions and returns a diff observation.

The core implementation is dependency-free and testable offline. Browser support is optional
and uses Playwright when installed.

## Current Implementation

Implemented from `Framework guide.md`:

- Unified `Element`, `Observation`, and `Action` schemas.
- Stable session IDs using role, normalized text, structural path, and quantized position.
- State store with keyframe and delta policy.
- Serializer with explicit token-budget degradation.
- ID, text, and coordinate resolver.
- Browser facade with optional Playwright sensor/executor.
- Anthropic/OpenAI tool schemas and dispatch adapters.
- Optional MCP server wrapper and `ocu serve` CLI.
- Minimal reference agent example.
- Offline fixtures and tests for the paper core.

## Quick Start

Pure core:

```python
from ocu import Element, StateStore
from ocu.serialize import observation_from_update

store = StateStore()
update = store.ingest([
    Element(id=0, role="button", text="Checkout", bbox=(20, 20, 120, 32), source="dom"),
])
obs = observation_from_update(update, max_tokens=1500)
print(obs.text)
```

Browser vertical slice:

```python
from ocu import Browser

env = Browser(start_url="https://example.com", max_obs_tokens=1500)
print(env.observe().text)
print(env.act("click", target=1).text)
env.close()
```

Install browser extras and Playwright browsers before using the browser facade:

```bash
python -m pip install ".[browser]"
python -m playwright install chromium
```

Manual live smoke test:

```bash
.venv/bin/python tests/live_browser_smoke.py
```

Provider-backed examples:

```bash
python -m pip install ".[providers,browser]"
python -m playwright install chromium
```

Select the model provider in `.env`:

```bash
# Google AI Studio / Gemini API
PROVIDER=google_ai_studio
GEMINI_API_KEY=your_ai_studio_key

# Or OpenRouter
PROVIDER=openrouter
OPENROUTER_API_KEY=your_openrouter_key
```

When `PROVIDER=google_ai_studio`, the examples use Google AI Studio through the
Gemini OpenAI-compatible endpoint with `gemini-3.5-flash`.

MCP:

```bash
ocu serve --target browser --start-url https://example.com --budget 1500
```

## Benchmarks

`benchmarks/webvoyager.py` runs a 30-task WebVoyager-style subset (books/quotes.toscrape,
Wikipedia, httpbin, arXiv, GitHub, example.com) with substring graders and real OpenRouter
usage metering. Three systems, same model, single-shot:

| System | tokens/step | tokens/task | $/task | success % | $/success |
|---|---:|---:|---:|---:|---:|
| browser-use (text mode) | 14122 | 23539 | $0.0016 | 96.7 | $0.0016 |
| ocu | 2450 | 8043 | $0.0005 | 90.0 | $0.0006 |
| screenshot loop | 786 | 6519 | $0.0005 | 13.3 | $0.0035 |

Model: `google/gemma-4-26b-a4b-it` ($0.06/M in, $0.33/M out), 2026-07-05. ocu uses 5.8x
fewer tokens per step and 2.9x fewer per task than browser-use and is 2.7x cheaper per
successful task, at 90% vs 96.7% success. The screenshot coordinate loop is the floor: cheap
but 13% successful at this model size. ocu's three remaining failures are model-capability
(the driver perseverates on refused clicks and answers one task from priors), not framework;
one of them is also browser-use's only failure.

Reproduce:

```bash
.venv/bin/python benchmarks/webvoyager.py --systems ocu,screenshot,browser-use \
  --out benchmarks/webvoyager_results.json
.venv/bin/python benchmarks/runner.py benchmarks/webvoyager_results.json
```
