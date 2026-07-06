from __future__ import annotations

from dataclasses import replace
from time import sleep
from typing import Any, Iterable, Mapping

from .executors import CdpExecutor, XdotoolExecutor
from .resolve import ResolutionError, Resolver
from .schema import Action, BBox, Element, Observation
from .sensors import AxLinuxSensor, BrowserSensor
from .serialize import estimate_tokens, observation_from_update
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

TEXT_SCRIPT = "() => document.body ? document.body.innerText : ''"

PROBE_SCRIPT = r"""
(arg) => {
  const out = {
    url: location.href,
    dialogs: document.querySelectorAll(
      'dialog[open],[role="alertdialog"]'
    ).length,
    rect: null
  };
  if (arg && arg.path) {
    let node = null;
    try { node = document.body.querySelector(":scope>" + arg.path); } catch (e) { node = null; }
    if (node) {
      let r = node.getBoundingClientRect();
      if (r.width > 0 && r.height > 0) {
        if (r.bottom < 0 || r.top > window.innerHeight || r.right < 0 || r.left > window.innerWidth) {
          node.scrollIntoView({ block: "center", inline: "center", behavior: "instant" });
          r = node.getBoundingClientRect();
        }
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
        if mode == "text":
            return self._observe_text()
        effective_mode = "region" if region is not None else mode
        frame = self._capture(region=region)
        update = self.state.ingest(frame.elements, url=frame.url, mode=effective_mode)
        return observation_from_update(update, max_tokens=self.max_obs_tokens)

    def _observe_text(self):
        try:
            raw = str(self.page.evaluate(TEXT_SCRIPT) or "")
        except Exception:
            raw = ""
        url = getattr(self.page, "url", None)
        header = f"## page text ({url})\n" if url else "## page text\n"
        limit = max(self.max_obs_tokens * 4 - len(header), 0)
        body = " ".join(raw.split())
        if len(body) > limit:
            body = body[:limit] + "\n... page text truncated"
        text = header + body
        return Observation(
            frame=self.state.frame,
            kind="key",
            text=text,
            elements=self.state.elements,
            tokens=estimate_tokens(text),
        )

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
        if len(coerced) > 16:
            raise ValueError(
                f"batch of {len(coerced)} actions rejected: send at most 16 distinct actions, "
                "never the same action repeated"
            )
        if not self.state.elements:
            self.observe(mode="full")

        try:
            self.page.wait_for_load_state("load", timeout=2000)
        except Exception:
            pass

        guard_active = guard == "abort_on_unexpected_change"
        baseline = self._probe(None) if guard_active and len(coerced) > 1 else None
        labels: list[str] = []

        for index, action in enumerate(coerced, start=1):
            if action.verb == "observe":
                mode = str(action.metadata.get("mode") or action.text or "full")
                return self.observe(mode=mode if mode in {"full", "text", "delta"} else "full")
            if action.verb == "done":
                return self.observe(mode="delta")

            if action.verb == "click" and action.target is not None:
                element = self.state.elements.get(action.target)
                if element is not None and not element.state.get("interactive", True):
                    near = self._nearest_interactive(element)
                    hint = f"; try [{near.id}] {near.role} '{near.text[:40]}'" if near else ""
                    return self._finish(
                        labels,
                        aborted_step=index,
                        note=f"click [{action.target}] refused: {element.role} is not interactive{hint}",
                    )

            probe = None
            if guard_active or action.target is not None:
                probe = self._probe(self._probe_path(action))
                if guard_active and index > 1:
                    reason = self._abort_reason(action, probe, baseline)
                    if reason:
                        return self._finish(labels, aborted_step=index, note=reason)

            relocated = None
            if (
                probe is not None
                and action.target is not None
                and self._probe_path(action)
                and probe.get("rect") is None
            ):
                relocated = self._relocate(action.target)
                if relocated is None:
                    return self._finish(
                        labels, aborted_step=index, note=f"target [{action.target}] disappeared"
                    )

            try:
                target = Resolver(self.state.elements).resolve(action)
                if probe and probe.get("rect") and action.target is not None:
                    x, y, width, height = probe["rect"]
                    target = replace(target, coordinate=(x + width // 2, y + height // 2))
                elif relocated is not None:
                    target = replace(target, coordinate=relocated)
                self.executor.execute(action, target)
            except Exception as exc:
                return self._finish(labels, aborted_step=index, note=f"{action.label()} failed: {exc}")
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
            self.page.wait_for_load_state("load", timeout=2000)
        except Exception:
            pass
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
        return None

    def _nearest_interactive(self, element):
        best = None
        for candidate in self.state.elements.values():
            if candidate.id == element.id or not candidate.state.get("interactive"):
                continue
            dx = candidate.center[0] - element.center[0]
            dy = candidate.center[1] - element.center[1]
            distance = dx * dx + dy * dy
            if best is None or distance < best[0]:
                best = (distance, candidate)
        return best[1] if best else None

    def _relocate(self, target_id: int) -> tuple[int, int] | None:
        return _relocate_element(self.sensor, self.state.elements, target_id)

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


def _relocate_element(sensor: Any, elements: Mapping[int, Element], target_id: int) -> tuple[int, int] | None:
    element = elements.get(target_id)
    if element is None:
        return None
    try:
        frame = sensor.capture()
    except Exception:
        return None
    best: tuple[int, tuple[int, int]] | None = None
    for candidate in frame.elements:
        if candidate.role != element.role or candidate.text != element.text:
            continue
        dx = candidate.center[0] - element.center[0]
        dy = candidate.center[1] - element.center[1]
        distance = dx * dx + dy * dy
        if best is None or distance < best[0]:
            best = (distance, candidate.center)
    return best[1] if best else None


class Desktop:
    def __init__(
        self,
        *,
        max_obs_tokens: int = 1500,
        keyframe_interval: int = 10,
        change_threshold: float = 0.40,
        settle_ms: int = 150,
        sensor: Any | None = None,
        executor: Any | None = None,
    ) -> None:
        self.max_obs_tokens = max_obs_tokens
        self.settle_ms = settle_ms
        self.state = StateStore(keyframe_interval=keyframe_interval, change_threshold=change_threshold)
        self.sensor = sensor if sensor is not None else AxLinuxSensor()
        self.executor = executor if executor is not None else XdotoolExecutor()

    def reset(self):
        self.state.reset()
        return self.observe(mode="full")

    def observe(self, mode: str = "auto", region: BBox | None = None):
        effective_mode = "region" if region is not None else mode
        frame = self.sensor.capture(region=region)
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
        if len(coerced) > 16:
            raise ValueError(
                f"batch of {len(coerced)} actions rejected: send at most 16 distinct actions, "
                "never the same action repeated"
            )
        if not self.state.elements:
            self.observe(mode="full")

        guard_active = guard == "abort_on_unexpected_change"
        labels: list[str] = []

        for index, action in enumerate(coerced, start=1):
            if action.verb == "observe":
                mode = str(action.metadata.get("mode") or action.text or "full")
                return self.observe(mode=mode if mode in {"full", "delta"} else "full")
            if action.verb == "done":
                return self.observe(mode="delta")

            relocated = None
            if guard_active and index > 1 and action.target is not None:
                relocated = _relocate_element(self.sensor, self.state.elements, action.target)
                if relocated is None:
                    return self._finish(
                        labels, aborted_step=index, note=f"target [{action.target}] disappeared"
                    )

            try:
                target = Resolver(self.state.elements).resolve(action)
                if relocated is not None:
                    target = replace(target, coordinate=relocated)
                self.executor.execute(action, target)
            except Exception as exc:
                return self._finish(labels, aborted_step=index, note=f"{action.label()} failed: {exc}")
            labels.append(action.label())

        return self._finish(labels)

    def screenshot(self, region: BBox | None = None) -> bytes:
        return self.sensor.screenshot(region=region)

    def close(self) -> None:
        return None

    def _finish(self, labels: list[str], *, aborted_step: int | None = None, note: str | None = None):
        if self.settle_ms:
            sleep(self.settle_ms / 1000)
        frame = self.sensor.capture()
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


__all__ = ["Browser", "Desktop", "FrameUpdate", "ResolutionError"]
