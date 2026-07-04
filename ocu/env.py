from __future__ import annotations

from dataclasses import replace
from typing import Any, Iterable, Mapping

from .executors import CdpExecutor
from .resolve import ResolutionError, Resolver
from .schema import Action, BBox
from .sensors import BrowserSensor
from .serialize import observation_from_update
from .state import FrameUpdate, StateStore


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
        **launch_options: Any,
    ) -> None:
        self.max_obs_tokens = max_obs_tokens
        self.state = StateStore(keyframe_interval=keyframe_interval, change_threshold=change_threshold)
        self._playwright = None
        self._browser = None
        self._owns_browser = False

        if page is None:
            page = self._new_page(browser_name=browser_name, headless=headless, launch_options=launch_options)
        self.page = page
        self.sensor = BrowserSensor(page)
        self.executor = CdpExecutor(page)

        if start_url:
            self.page.goto(start_url, wait_until="domcontentloaded")

    def reset(self, start_url: str | None = None):
        self.state.reset()
        if start_url:
            self.page.goto(start_url, wait_until="domcontentloaded")
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
        if not self.state.elements:
            self.observe(mode="full")

        last_update: FrameUpdate | None = None
        for index, action in enumerate(coerced, start=1):
            if action.verb == "observe":
                return self.observe(mode="full")
            if action.verb == "done":
                return self.observe(mode="delta")

            resolver = Resolver(self.state.elements)
            target = resolver.resolve(action)
            self.executor.execute(action, target)
            sensor_frame = self.sensor.capture()
            last_update = self.state.ingest(sensor_frame.elements, url=sensor_frame.url, last_action=action.label())

            if guard == "abort_on_unexpected_change" and index < len(coerced):
                abort_reason = self._guard_abort_reason(action, last_update)
                if abort_reason:
                    aborted = replace(
                        last_update,
                        last_action=f"{action.label()} ({abort_reason})",
                        aborted_step=index,
                    )
                    return observation_from_update(aborted, max_tokens=self.max_obs_tokens)

        if last_update is None:
            raise RuntimeError("action batch did not execute")
        return observation_from_update(last_update, max_tokens=self.max_obs_tokens)

    def screenshot(self, region: BBox | None = None) -> bytes:
        return self.sensor.screenshot(region=region)

    def close(self) -> None:
        if self._owns_browser and self._browser is not None:
            self._browser.close()
        if self._playwright is not None:
            self._playwright.stop()

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

    def _guard_abort_reason(self, action: Action, update: FrameUpdate) -> str | None:
        if action.target is not None and action.target not in update.elements:
            return f"target [{action.target}] disappeared"
        if any(element.role in {"dialog", "alert"} for element in update.diff.added):
            return "dialog_or_alert_appeared"
        if update.kind == "key" and update.reason in {"url_changed", "change_threshold"}:
            return update.reason
        return None


class Desktop:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise NotImplementedError("Desktop support is planned for phase 2")


__all__ = ["Browser", "Desktop", "ResolutionError"]
