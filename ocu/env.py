from __future__ import annotations

from dataclasses import replace
from time import sleep
from typing import Any, Iterable, Mapping

from .executors import CdpExecutor
from .resolve import ResolutionError, Resolver
from .schema import Action, BBox
from .sensors import BrowserSensor
from .serialize import observation_from_update
from .state import FrameUpdate, StateStore

BLOCKED_URL_PATTERNS = [
    "*.png",
    "*.jpg",
    "*.jpeg",
    "*.gif",
    "*.webp",
    "*.avif",
    "*.ico",
    "*.woff",
    "*.woff2",
    "*.ttf",
    "*.otf",
    "*.mp4",
    "*.webm",
    "*.mp3",
    "*.m4a",
    "*.ogg",
    "*googletagmanager.com*",
    "*google-analytics.com*",
    "*doubleclick.net*",
    "*connect.facebook.net*",
    "*hotjar.com*",
]

PROBE_SCRIPT = r"""
(arg) => {
  const out = {
    url: location.href,
    dialogs: document.querySelectorAll(
      'dialog[open],[role="dialog"],[role="alertdialog"],[role="alert"]'
    ).length,
    rect: null
  };
  if (arg && arg.path) {
    let node = null;
    try { node = document.body.querySelector(":scope>" + arg.path); } catch (e) { node = null; }
    if (node) {
      const r = node.getBoundingClientRect();
      if (r.width > 0 && r.height > 0) {
        out.rect = [Math.round(r.left), Math.round(r.top), Math.round(r.width), Math.round(r.height)];
      }
    }
  }
  return out;
}
"""


class Browser:
    def __init__(
        self,
        *,
        start_url: str | None = None,
        max_obs_tokens: int = 1500,
        page: Any | None = None,
        headless: bool = True,
        browser_name: str = "chromium",
        keyframe_interval: int = 10,
        change_threshold: float = 0.40,
        include_ax: bool = False,
        settle_ms: int = 150,
        settle_quiet_ms: int = 20,
        block_resources: bool = True,
        **launch_options: Any,
    ) -> None:
        self.max_obs_tokens = max_obs_tokens
        self.settle_ms = settle_ms
        self.settle_quiet_ms = settle_quiet_ms
        self.state = StateStore(keyframe_interval=keyframe_interval, change_threshold=change_threshold)
        self._playwright = None
        self._browser = None
        self._owns_browser = False

        if page is None:
            page = self._new_page(browser_name=browser_name, headless=headless, launch_options=launch_options)
        self.page = page
        self.sensor = BrowserSensor(page, include_ax=include_ax)
        self.executor = CdpExecutor(page)
        if block_resources:
            self._block_resources()

        if start_url:
            self.page.goto(start_url, wait_until="domcontentloaded")

    def reset(self, start_url: str | None = None):
        self.state.reset()
        if start_url:
            self.page.goto(start_url, wait_until="domcontentloaded")
        return self.observe(mode="full")

    def observe(self, mode: str = "auto", region: BBox | None = None):
        effective_mode = "region" if region is not None else mode
        frame = self._capture(region=region)
        update = self.state.ingest(frame.elements, url=frame.url, mode=effective_mode)
        return observation_from_update(update, max_tokens=self.max_obs_tokens)

    def act(
        self,
        verb: str | Action | Mapping[str, Any],
        *,
        target: int | None = None,
        coordinate: tuple[int, int] | None = None,
        text: str | None = None,
        guard: str = "abort_on_unexpected_change",
        **metadata: Any,
    ):
        if isinstance(verb, str):
            action = Action(verb=verb, target=target, coordinate=coordinate, text=text, metadata=metadata)
        else:
            action = Action.coerce(verb)
        return self.act_batch([action], guard=guard)

    def act_batch(
        self,
        actions: Iterable[Action | Mapping[str, Any]],
        *,
        guard: str = "abort_on_unexpected_change",
    ):
        coerced = [Action.coerce(action) for action in actions]
        if not coerced:
            return self.observe(mode="delta")
        if not self.state.elements:
            self.observe(mode="full")

        guard_active = guard == "abort_on_unexpected_change"
        baseline = self._probe(None) if guard_active and len(coerced) > 1 else None
        labels: list[str] = []

        for index, action in enumerate(coerced, start=1):
            if action.verb == "observe":
                return self.observe(mode="full")
            if action.verb == "done":
                return self.observe(mode="delta")

            probe = None
            if index > 1 and (guard_active or action.target is not None):
                probe = self._probe(self._probe_path(action))
                if guard_active:
                    reason = self._abort_reason(action, probe, baseline)
                    if reason:
                        return self._finish(labels, aborted_step=index, note=reason)

            target = Resolver(self.state.elements).resolve(action)
            if probe and probe.get("rect") and action.target is not None:
                x, y, width, height = probe["rect"]
                target = replace(target, coordinate=(x + width // 2, y + height // 2))
            self.executor.execute(action, target)
            labels.append(action.label())

        return self._finish(labels)

    def screenshot(self, region: BBox | None = None) -> bytes:
        return self.sensor.screenshot(region=region)

    def close(self) -> None:
        if self._owns_browser and self._browser is not None:
            self._browser.close()
        if self._playwright is not None:
            self._playwright.stop()

    def _finish(self, labels: list[str], *, aborted_step: int | None = None, note: str | None = None):
        frame = self._capture(settle={"quiet": self.settle_quiet_ms, "max": self.settle_ms})
        last_action = "; ".join(labels) if labels else None
        if note:
            last_action = f"{last_action} ({note})" if last_action else note
        update = self.state.ingest(
            frame.elements,
            url=frame.url,
            last_action=last_action,
            aborted_step=aborted_step,
        )
        return observation_from_update(update, max_tokens=self.max_obs_tokens)

    def _capture(self, region: BBox | None = None, settle: dict[str, int] | None = None):
        try:
            return self.sensor.capture(region=region, settle=settle)
        except Exception:
            try:
                self.page.wait_for_load_state("domcontentloaded")
            except Exception:
                sleep(0.08)
            return self.sensor.capture(region=region, settle=settle)

    def _block_resources(self) -> None:
        client = getattr(self.executor, "_client", None)
        if client is None:
            return
        try:
            client.send("Network.enable", {})
            client.send("Network.setBlockedURLs", {"urls": BLOCKED_URL_PATTERNS})
        except Exception:
            pass

    def _probe(self, path: str | None) -> dict[str, Any] | None:
        try:
            return self.page.evaluate(PROBE_SCRIPT, {"path": path})
        except Exception:
            return None

    def _probe_path(self, action: Action) -> str | None:
        if action.target is None:
            return None
        element = self.state.elements.get(action.target)
        if element is None:
            return None
        path = element.state.get("structural_path")
        if not path or str(path).startswith("ax"):
            return None
        return str(path)

    def _abort_reason(self, action: Action, probe: dict[str, Any] | None, baseline: dict[str, Any] | None) -> str | None:
        if probe is None:
            return "navigation"
        if baseline is not None:
            if probe.get("url") != baseline.get("url"):
                return "url_changed"
            if int(probe.get("dialogs") or 0) > int(baseline.get("dialogs") or 0):
                return "dialog_or_alert_appeared"
        if action.target is not None and self._probe_path(action) and probe.get("rect") is None:
            return f"target [{action.target}] disappeared"
        return None

    def _new_page(self, *, browser_name: str, headless: bool, launch_options: dict[str, Any]) -> Any:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError(
                "Browser requires the optional Playwright dependency. "
                'Install with: python -m pip install ".[browser]"'
            ) from exc

        self._playwright = sync_playwright().start()
        browser_type = getattr(self._playwright, browser_name)
        self._browser = browser_type.launch(headless=headless, **launch_options)
        self._owns_browser = True
        return self._browser.new_page()


class Desktop:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise NotImplementedError("Desktop support is planned for phase 2")


__all__ = ["Browser", "Desktop", "FrameUpdate", "ResolutionError"]
