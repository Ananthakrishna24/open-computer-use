from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from typing import Any, Iterator

from ..schema import BBox, Element, INTERACTIVE_ROLES, normalize_text
from .base import SensorFrame, filter_region

ROLE_MAP = {
    "push button": "button",
    "toggle button": "button",
    "button": "button",
    "check box": "checkbox",
    "radio button": "radio",
    "menu item": "menuitem",
    "check menu item": "menuitem",
    "radio menu item": "menuitem",
    "page tab": "tab",
    "combo box": "combobox",
    "spin button": "spinbutton",
    "slider": "slider",
    "entry": "input",
    "password text": "input",
    "link": "link",
    "label": "text",
    "static": "text",
    "heading": "text",
    "paragraph": "text",
    "list item": "option",
    "icon": "image",
    "image": "image",
}

MAX_DEPTH = 60
MAX_ELEMENTS = 5000

SCREENSHOT_COMMANDS = [
    ("maim", lambda path, region: ["maim", "-g", f"{region[2]}x{region[3]}+{region[0]}+{region[1]}", path] if region else ["maim", path]),
    ("scrot", lambda path, region: ["scrot", "-o", "-a", f"{region[0]},{region[1]},{region[2]},{region[3]}", path] if region else ["scrot", "-o", path]),
    ("import", lambda path, region: ["import", "-window", "root", "-crop", f"{region[2]}x{region[3]}+{region[0]}+{region[1]}", path] if region else ["import", "-window", "root", path]),
]


class AxLinuxSensor:
    def __init__(self, *, desktop: Any | None = None) -> None:
        self._desktop = desktop

    def capture(self, region: BBox | None = None) -> SensorFrame:
        desktop = self._desktop if self._desktop is not None else _load_desktop()
        elements: list[Element] = []
        for index, application in enumerate(_children(desktop), start=1):
            _walk(application, f"ax>app[{index}]", elements, depth=0)
            if len(elements) >= MAX_ELEMENTS:
                break
        return SensorFrame(elements=filter_region(elements, region))

    def screenshot(self, region: BBox | None = None) -> bytes:
        handle, path = tempfile.mkstemp(suffix=".png")
        os.close(handle)
        try:
            for name, build in SCREENSHOT_COMMANDS:
                if shutil.which(name) is None:
                    continue
                result = subprocess.run(build(path, region), capture_output=True)
                if result.returncode == 0 and os.path.getsize(path) > 0:
                    with open(path, "rb") as file:
                        return file.read()
            raise RuntimeError(
                "no screenshot tool found: install maim, scrot, or imagemagick (import)"
            )
        finally:
            os.unlink(path)


def _load_desktop() -> Any:
    try:
        import pyatspi

        return pyatspi.Registry.getDesktop(0)
    except ImportError:
        pass
    try:
        import gi

        gi.require_version("Atspi", "2.0")
        from gi.repository import Atspi

        Atspi.init()
        return Atspi.get_desktop(0)
    except Exception as exc:
        raise RuntimeError(
            "AT-SPI is unavailable: install pyatspi or python3-gi + gir1.2-atspi-2.0 "
            "and run inside an accessible X11 session"
        ) from exc


def _walk(node: Any, path: str, out: list[Element], *, depth: int) -> None:
    if depth > MAX_DEPTH or len(out) >= MAX_ELEMENTS:
        return
    raw_role = normalize_text(_attr(node, "getRoleName", "get_role_name")).lower()
    if raw_role != "application":
        states = _state_names(node)
        if "visible" not in states or "showing" not in states:
            return
        _emit(node, raw_role, states, path, out)
    for index, child in enumerate(_children(node), start=1):
        _walk(child, f"{path}>{raw_role or 'node'}[{index}]", out, depth=depth + 1)


def _emit(node: Any, raw_role: str, states: set[str], path: str, out: list[Element]) -> None:
    bbox = _extents(node)
    if bbox[2] <= 0 or bbox[3] <= 0:
        return
    role = _map_role(raw_role, states)
    interactive = role in INTERACTIVE_ROLES or "editable" in states
    text = normalize_text(_attr(node, "name", "get_name", default=""))
    if not text and (interactive or role == "text"):
        text = normalize_text(_text_content(node))
    if not text:
        text = normalize_text(_attr(node, "description", "get_description", default=""))
    child_count = int(_attr(node, "childCount", "get_child_count", default=0) or 0)
    if not interactive and (not text or child_count > 0 or len(text) > 500):
        return

    state: dict[str, Any] = {"visible": True, "interactive": interactive, "structural_path": path}
    if "focused" in states:
        state["focused"] = True
    if interactive and "sensitive" not in states and "enabled" not in states:
        state["disabled"] = True
    if "checked" in states:
        state["checked"] = True
    elif role in {"checkbox", "radio", "switch"}:
        state["checked"] = False
    if "selected" in states:
        state["selected"] = True
    if "expanded" in states:
        state["expanded"] = True
    if role == "input":
        value = normalize_text(_text_content(node))
        if value and value != text:
            state["value"] = value

    out.append(Element(id=0, role=role, text=text, bbox=bbox, source="ax", state=state))


def _map_role(raw_role: str, states: set[str]) -> str:
    if raw_role == "text":
        return "input" if "editable" in states else "text"
    return ROLE_MAP.get(raw_role, raw_role or "unknown")


def _attr(node: Any, *names: str, default: Any = None) -> Any:
    for name in names:
        value = getattr(node, name, None)
        if value is None:
            continue
        if callable(value):
            try:
                value = value()
            except Exception:
                continue
        if value is not None:
            return value
    return default


def _children(node: Any) -> Iterator[Any]:
    count = int(_attr(node, "childCount", "get_child_count", default=0) or 0)
    getter = getattr(node, "getChildAtIndex", None) or getattr(node, "get_child_at_index", None)
    if getter is None:
        return
    for index in range(min(count, 1024)):
        try:
            child = getter(index)
        except Exception:
            continue
        if child is not None:
            yield child


def _state_names(node: Any) -> set[str]:
    stateset = _attr(node, "getState", "get_state_set")
    if stateset is None:
        return set()
    states = _attr(stateset, "getStates", "get_states", default=[]) or []
    names: set[str] = set()
    for state in states:
        nick = getattr(state, "value_nick", None)
        if nick:
            names.add(str(nick).replace("-", "_").lower())
            continue
        name = getattr(state, "value_name", None) or str(state)
        names.add(str(name).split("STATE_")[-1].replace("-", "_").lower())
    return names


def _extents(node: Any) -> BBox:
    for getter in ("queryComponent", "get_component_iface", "get_component"):
        query = getattr(node, getter, None)
        if query is None:
            continue
        try:
            component = query()
        except Exception:
            continue
        if component is None:
            continue
        for extents_getter in ("getExtents", "get_extents"):
            fetch = getattr(component, extents_getter, None)
            if fetch is None:
                continue
            try:
                extents = fetch(0)
            except Exception:
                continue
            return (
                int(getattr(extents, "x", 0)),
                int(getattr(extents, "y", 0)),
                int(getattr(extents, "width", 0)),
                int(getattr(extents, "height", 0)),
            )
    return (0, 0, 0, 0)


def _text_content(node: Any) -> str:
    for getter in ("queryText", "get_text_iface"):
        query = getattr(node, getter, None)
        if query is None:
            continue
        try:
            text_iface = query()
        except Exception:
            continue
        if text_iface is None:
            continue
        count = int(_attr(text_iface, "characterCount", "get_character_count", default=0) or 0)
        for text_getter in ("getText", "get_text"):
            fetch = getattr(text_iface, text_getter, None)
            if fetch is None:
                continue
            try:
                return str(fetch(0, count) or "")
            except Exception:
                continue
    return ""
