from __future__ import annotations

from time import sleep
from typing import Any

from ..resolve import ResolvedTarget
from ..schema import Action

FOCUS_SCRIPT = (
    "() => { const el = document.activeElement;"
    " return Boolean(el && (el.isContentEditable"
    " || el.tagName === 'INPUT' || el.tagName === 'TEXTAREA')); }"
)

SELECT_ALL_SCRIPT = (
    "() => { const el = document.activeElement;"
    " if (!el) return false;"
    " if ((el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') && el.value)"
    " { el.select(); return true; }"
    " if (el.isContentEditable && el.textContent)"
    " { window.getSelection().selectAllChildren(el); return true; }"
    " return false; }"
)


class CdpExecutor:
    def __init__(self, page: Any) -> None:
        self.page = page
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
        elif action.verb == "goto":
            self._goto(action)
        elif action.verb == "back":
            self._back()
        elif action.verb in {"observe", "done"}:
            return
        else:
            raise ValueError(f"unsupported action verb {action.verb!r}")

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
        self._wait_for_editable_focus()
        try:
            self.page.evaluate(SELECT_ALL_SCRIPT)
        except Exception:
            pass
        text = action.text or ""
        if self._client is not None:
            self._client.send("Input.insertText", {"text": text})
        else:
            self.page.keyboard.insert_text(text)

    def _wait_for_editable_focus(self, timeout_ms: int = 600) -> None:
        deadline = timeout_ms
        while deadline > 0:
            try:
                if self.page.evaluate(FOCUS_SCRIPT):
                    return
            except Exception:
                return
            self._wait(Action(verb="wait", metadata={"ms": 50}))
            deadline -= 50

    def _press(self, action: Action) -> None:
        key = action.text or action.metadata.get("key") or action.metadata.get("press")
        if not key:
            raise ValueError('press needs the key name in text: {"verb": "press", "text": "Escape"}')
        self.page.keyboard.press(str(key))

    def _scroll(self, action: Action, target: ResolvedTarget) -> None:
        if target.coordinate is not None:
            self.page.mouse.move(*target.coordinate)
        dx = int(action.metadata.get("dx", action.metadata.get("delta_x", 0)))
        dy = int(action.metadata.get("dy", action.metadata.get("delta_y", 500)))
        self.page.mouse.wheel(dx, dy)

    def _drag(self, action: Action, target: ResolvedTarget) -> None:
        if target.coordinate is None:
            raise ValueError("drag requires a start: coordinate [x, y] (or a target id)")
        end = _point(action.metadata.get("to") or action.metadata.get("end"))
        if end is None:
            raise ValueError('drag needs both corners: {"verb": "drag", "coordinate": [x1, y1], "to": [x2, y2]}')
        start_x, start_y = target.coordinate
        end_x, end_y = end
        self.page.mouse.move(start_x, start_y)
        self.page.mouse.down()
        self.page.mouse.move(end_x, end_y, steps=12)
        self.page.mouse.up()

    def _goto(self, action: Action) -> None:
        url = action.text or action.metadata.get("url")
        if not url:
            raise ValueError("goto requires a url in text")
        url = str(url)
        if "://" not in url:
            url = "https://" + url
        self.page.goto(url, wait_until="domcontentloaded")

    def _back(self) -> None:
        self.page.go_back(wait_until="domcontentloaded")

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


def _point(value: Any) -> tuple[int, int] | None:
    if isinstance(value, dict):
        value = (value.get("x"), value.get("y"))
    if isinstance(value, (list, tuple)) and len(value) == 2 and None not in value:
        return (int(value[0]), int(value[1]))
    return None
