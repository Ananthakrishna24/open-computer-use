from __future__ import annotations

from pathlib import Path
from typing import Any

from ocu.env import TEXT_SCRIPT

DEFAULT_PROFILE = Path.home() / ".cache" / "ocu-agent" / "profile"

CHALLENGE_MARKERS = (
    "verify you are human",
    "verify you're human",
    "unusual traffic",
    "captcha",
    "just a moment",
    "checking your browser",
    "are you a robot",
    "attention required",
    "access denied",
)


def looks_blocked(observation: str) -> bool:
    lowered = observation.casefold()
    return any(marker in lowered for marker in CHALLENGE_MARKERS)


def page_text(page: Any) -> str:
    return str(page.evaluate(TEXT_SCRIPT) or "")


def read_page(raw: str, *, query: str | None = None, page: int = 0, chunk_chars: int = 6000) -> str:
    body = " ".join(str(raw or "").split())
    if not body:
        return "page has no readable text"
    total = (len(body) + chunk_chars - 1) // chunk_chars
    index = max(0, min(int(page), total - 1))
    if query:
        position = body.casefold().find(str(query).casefold())
        if position < 0:
            return f'"{query}" not found in page text ({total} parts)'
        index = position // chunk_chars
    start = index * chunk_chars
    header = f"## page text (part {index + 1}/{total})"
    return header + "\n" + body[start : start + chunk_chars]


def launch_page(
    profile_dir: str | Path = DEFAULT_PROFILE,
    *,
    headless: bool = False,
    slow_mo: int = 60,
) -> tuple[Any, Any, Any]:
    from playwright.sync_api import sync_playwright

    Path(profile_dir).mkdir(parents=True, exist_ok=True)
    playwright = sync_playwright().start()
    options = dict(
        headless=headless,
        slow_mo=slow_mo,
        viewport={"width": 1366, "height": 768},
        args=["--disable-blink-features=AutomationControlled"],
        ignore_default_args=["--enable-automation"],
    )
    try:
        context = playwright.chromium.launch_persistent_context(str(profile_dir), channel="chrome", **options)
    except Exception:
        context = playwright.chromium.launch_persistent_context(str(profile_dir), **options)
    page = context.pages[0] if context.pages else context.new_page()
    return playwright, context, page
