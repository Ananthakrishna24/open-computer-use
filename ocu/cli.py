from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ocu")
    subparsers = parser.add_subparsers(dest="command", required=True)

    serve = subparsers.add_parser("serve", help="run an MCP server")
    serve.add_argument("--target", choices=["browser"], required=True)
    serve.add_argument("--start-url", required=True)
    serve.add_argument("--budget", type=int, default=1500)
    serve.add_argument("--browser", default="chromium", choices=["chromium", "firefox", "webkit"])
    serve.add_argument("--headed", action="store_true", help="show the browser window")
    serve.add_argument("--ax", action="store_true", help="merge accessibility snapshots (slower)")
    serve.add_argument("--settle-ms", type=int, default=150, help="max post-action settle wait")
    serve.add_argument("--quiet-ms", type=int, default=20, help="mutation quiet window before capture")
    serve.add_argument("--all-assets", action="store_true", help="load images, fonts, media, trackers")

    args = parser.parse_args(argv)
    if args.command == "serve":
        from .integrations.mcp_server import serve_browser

        try:
            serve_browser(
                start_url=args.start_url,
                budget=args.budget,
                headless=not args.headed,
                browser_name=args.browser,
                include_ax=args.ax,
                settle_ms=args.settle_ms,
                settle_quiet_ms=args.quiet_ms,
                block_resources=not args.all_assets,
            )
        except Exception as exc:
            print(f"ocu: {exc}", file=sys.stderr)
            return 1
        return 0

    parser.error(f"unknown command {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
