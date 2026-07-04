from __future__ import annotations

from time import sleep
from typing import Any

from ..resolve import ResolvedTarget
from ..schema import Action


class CdpExecutor:
    def __init__(self, page: Any, *, post_action_delay: float = 0.05) -> None:
        self.page = page
        self.post_action_delay = post_action_delay
        self._client = self._make_cdp_client(page)

    def execute(self, action: Action, target: ResolvedTarget) -> None:
        if action.verb == "click":
            self._click(target)
        elif action.verb == "type":
            self._type(action, target)
        elif action.verb == "press":
            self._press(action)
        elif action.verb == "scroll":
            self._scroll(action, target)
        elif action.verb == "drag":
            self._drag(action, target)
        elif action.verb == "wait":
            self._wait(action)
        elif action.verb in {"observe", "done"}:
            return
        else:
            raise ValueError(f"unsupported action verb {action.verb!r}")
        if self.post_action_delay:
            sleep(self.post_action_delay)

    def _click(self, target: ResolvedTarget) -> None:
        if target.coordinate is None:
            raise ValueError("click requires a resolved coordinate")
        x, y = target.coordinate
        if self._client is not None:
            self._client.send("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y})
            self._client.send(
                "Input.dispatchMouseEvent",
                {"type": "mousePressed", "x": x, "y": y, "button": "left", "clickCount": 1},
            )
            self._client.send(
                "Input.dispatchMouseEvent",
                {"type": "mouseReleased", "x": x, "y": y, "button": "left", "clickCount": 1},
            )
        else:
            self.page.mouse.click(x, y)

    def _type(self, action: Action, target: ResolvedTarget) -> None:
        if target.coordinate is not None:
            self._click(target)
        text = action.text or ""
        if self._client is not None:
            self._client.send("Input.insertText", {"text": text})
        else:
            self.page.keyboard.insert_text(text)

    def _press(self, action: Action) -> None:
        key = action.text or action.metadata.get("key")
        if not key:
            raise ValueError("press requires text/key")
        self.page.keyboard.press(str(key))

    def _scroll(self, action: Action, target: ResolvedTarget) -> None:
        if target.coordinate is not None:
            self.page.mouse.move(*target.coordinate)
        dx = int(action.metadata.get("dx", action.metadata.get("delta_x", 0)))
        dy = int(action.metadata.get("dy", action.metadata.get("delta_y", 500)))
        self.page.mouse.wheel(dx, dy)

    def _drag(self, action: Action, target: ResolvedTarget) -> None:
        if target.coordinate is None:
            raise ValueError("drag requires a resolved start coordinate")
        end = action.metadata.get("to") or action.metadata.get("end")
        if not end or len(end) != 2:
            raise ValueError("drag requires metadata {'to': [x, y]}")
        start_x, start_y = target.coordinate
        end_x, end_y = int(end[0]), int(end[1])
        self.page.mouse.move(start_x, start_y)
        self.page.mouse.down()
        self.page.mouse.move(end_x, end_y)
        self.page.mouse.up()

    def _wait(self, action: Action) -> None:
        milliseconds = int(action.metadata.get("ms", action.metadata.get("milliseconds", 500)))
        if hasattr(self.page, "wait_for_timeout"):
            self.page.wait_for_timeout(milliseconds)
        else:
            sleep(milliseconds / 1000)

    def _make_cdp_client(self, page: Any) -> Any | None:
        try:
            return page.context.new_cdp_session(page)
        except Exception:
            return None
