from __future__ import annotations

from typing import Any

from ..env import Browser


def create_server(env: Any, *, name: str = "open-computer-use") -> Any:
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:
        raise RuntimeError('MCP support requires the optional dependency: python -m pip install ".[mcp]"') from exc

    mcp = FastMCP(name)

    @mcp.tool()
    def observe(mode: str = "full", region: list[int] | None = None) -> str:
        return env.observe(mode=mode, region=tuple(region) if region else None).text

    @mcp.tool()
    def act(actions: list[dict[str, Any]], guard: str = "abort_on_unexpected_change") -> str:
        return env.act_batch(actions, guard=guard).text

    return mcp


def serve_browser(
    *,
    start_url: str,
    budget: int = 1500,
    headless: bool = True,
    browser_name: str = "chromium",
    include_ax: bool = False,
    settle_ms: int = 150,
    settle_quiet_ms: int = 20,
    block_resources: bool = True,
) -> None:
    env = Browser(
        start_url=start_url,
        max_obs_tokens=budget,
        headless=headless,
        browser_name=browser_name,
        include_ax=include_ax,
        settle_ms=settle_ms,
        settle_quiet_ms=settle_quiet_ms,
        block_resources=block_resources,
    )
    try:
        create_server(env).run()
    finally:
        env.close()
