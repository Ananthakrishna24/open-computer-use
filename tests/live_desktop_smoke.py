from __future__ import annotations

import os
import shutil

from ocu import Desktop
from ocu.sensors.ax_linux import _load_desktop


def available() -> str | None:
    wayland = bool(os.environ.get("WAYLAND_DISPLAY"))
    if not wayland and not os.environ.get("DISPLAY"):
        return "no display session (neither WAYLAND_DISPLAY nor DISPLAY set)"
    tool = "ydotool" if wayland else "xdotool"
    if shutil.which(tool) is None:
        return f"{tool} is not installed"
    try:
        _load_desktop()
    except RuntimeError as exc:
        return str(exc)
    return None


def main() -> int:
    reason = available()
    if reason:
        print(f"live desktop smoke skipped: {reason}")
        return 0
    desktop = Desktop(max_obs_tokens=1500)
    first = desktop.observe(mode="full")
    assert first.kind == "key", first.text
    assert first.elements, "AT-SPI returned no elements; is accessibility enabled?"
    print(first.text)
    second = desktop.act("wait", ms=100)
    assert second.kind in {"key", "delta"}, second.text
    assert "did: wait" in second.text, second.text
    print(second.text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
