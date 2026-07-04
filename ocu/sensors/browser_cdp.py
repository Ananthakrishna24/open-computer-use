from __future__ import annotations

from typing import Any

from ..schema import BBox, Element, normalize_role, normalize_text
from .base import SensorFrame

DOM_SNAPSHOT_SCRIPT = r"""
async (arg) => {
  const region = arg && arg.region;
  const settle = arg && arg.settle;
  const root = document.documentElement;
  if (settle && root) {
    await new Promise((resolve) => {
      let quietTimer = 0;
      const observer = new MutationObserver(() => {
        clearTimeout(quietTimer);
        quietTimer = setTimeout(done, settle.quiet);
      });
      const capTimer = setTimeout(done, settle.max);
      function done() {
        observer.disconnect();
        clearTimeout(quietTimer);
        clearTimeout(capTimer);
        resolve();
      }
      observer.observe(root, {
        subtree: true, childList: true, attributes: true, characterData: true
      });
      quietTimer = setTimeout(done, settle.quiet);
    });
  }
  const interactiveRoles = new Set([
    "button", "link", "input", "textbox", "textarea", "searchbox", "checkbox",
    "radio", "switch", "combobox", "select", "menuitem", "tab", "slider",
    "spinbutton", "option"
  ]);
  const canCheck = typeof Element.prototype.checkVisibility === "function";
  const elements = [];

  function clean(text) {
    return String(text || "").replace(/\s+/g, " ").trim();
  }

  function proxiedControl(node, tag) {
    if (tag !== "label" || !node.control) return null;
    if (canCheck && node.control.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true })) {
      return null;
    }
    return node.control;
  }

  function roleFor(node, tag) {
    const explicit = clean(node.getAttribute("role")).toLowerCase();
    if (explicit) return explicit;
    const type = clean(node.getAttribute("type")).toLowerCase();
    const control = proxiedControl(node, tag);
    if (control) {
      const controlType = clean(control.type).toLowerCase();
      if (controlType === "radio") return "radio";
      if (controlType === "checkbox") return "checkbox";
      return "button";
    }
    if (tag === "a" && node.hasAttribute("href")) return "link";
    if (tag === "button" || type === "button" || type === "submit" || type === "reset") return "button";
    if (tag === "textarea") return "textarea";
    if (tag === "select") return "combobox";
    if (tag === "input") {
      if (type === "checkbox") return "checkbox";
      if (type === "radio") return "radio";
      if (type === "range") return "slider";
      if (type === "search") return "searchbox";
      return "input";
    }
    if (tag === "img") return "image";
    if (tag === "canvas") return "canvas";
    return "text";
  }

  function labelFor(node, role, tag) {
    const aria = clean(node.getAttribute("aria-label"));
    if (aria) return aria;
    const labelledBy = clean(node.getAttribute("aria-labelledby"));
    if (labelledBy) {
      const labels = labelledBy.split(/\s+/).map((id) => {
        const target = document.getElementById(id);
        return target ? clean(target.innerText || target.textContent) : "";
      }).filter(Boolean).join(" ");
      if (labels) return labels;
    }
    const title = clean(node.getAttribute("title"));
    if (title) return title;
    if ((tag === "input" || tag === "textarea") && interactiveRoles.has(role)) {
      return clean(node.placeholder || "");
    }
    const alt = clean(node.getAttribute("alt"));
    if (alt) return alt;
    return clean(node.innerText || node.textContent);
  }

  function intersectsRegion(rect) {
    if (!region) return true;
    return rect.left < region.x + region.width &&
      rect.right > region.x &&
      rect.top < region.y + region.height &&
      rect.bottom > region.y;
  }

  function emit(node, tag, path) {
    const rect = node.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0 || !intersectsRegion(rect)) return;
    const role = roleFor(node, tag);
    const text = labelFor(node, role, tag);
    const interactive = interactiveRoles.has(role) ||
      role === "canvas" ||
      node.hasAttribute("onclick") ||
      (node.hasAttribute("tabindex") && node.getAttribute("tabindex") !== "-1");

    if (!interactive && !text) return;
    if (!interactive && node.childElementCount > 0) return;
    if (!interactive && text.length > 500) return;

    const state = {
      visible: true,
      interactive,
      structural_path: path
    };
    if (node === document.activeElement) state.focused = true;
    if ("disabled" in node && node.disabled) state.disabled = true;
    if ("checked" in node) state.checked = Boolean(node.checked);
    const control = proxiedControl(node, tag);
    if (control && "checked" in control) state.checked = Boolean(control.checked);
    if ("value" in node && interactive) state.value = clean(node.value || "");
    if (node.getAttribute("aria-selected") === "true") state.selected = true;

    elements.push({
      role,
      text,
      bbox: [Math.round(rect.left), Math.round(rect.top), Math.round(rect.width), Math.round(rect.height)],
      source: "dom",
      state
    });
  }

  function walk(parent, parentPath, hidden) {
    const counts = {};
    for (let node = parent.firstElementChild; node; node = node.nextElementSibling) {
      const tag = node.tagName.toLowerCase();
      counts[tag] = (counts[tag] || 0) + 1;
      const step = tag + ":nth-of-type(" + counts[tag] + ")";
      const path = parentPath ? parentPath + ">" + step : step;

      let nodeHidden = hidden;
      if (canCheck && node.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true })) {
        nodeHidden = false;
      } else {
        const style = window.getComputedStyle(node);
        if (style.display === "none" || Number(style.opacity) === 0) continue;
        nodeHidden = canCheck ? true : (hidden || style.visibility === "hidden");
      }

      if (!nodeHidden) emit(node, tag, path);
      walk(node, path, nodeHidden);
    }
  }

  if (document.body) {
    walk(document.body, "", false);
  }

  return {
    url: window.location.href,
    viewport_size: [window.innerWidth, window.innerHeight],
    device_scale_factor: window.devicePixelRatio || 1,
    elements
  };
}
"""


class BrowserSensor:
    def __init__(self, page: Any, *, include_ax: bool = False) -> None:
        self.page = page
        self.include_ax = include_ax

    def capture(self, region: BBox | None = None, settle: dict[str, int] | None = None) -> SensorFrame:
        payload = self.page.evaluate(DOM_SNAPSHOT_SCRIPT, {"region": _region_arg(region), "settle": settle})
        dom_elements = [
            Element(
                id=0,
                role=item.get("role", "text"),
                text=item.get("text", ""),
                bbox=item.get("bbox", (0, 0, 0, 0)),
                source=item.get("source", "dom"),
                state=item.get("state", {}),
            )
            for item in payload.get("elements", [])
        ]
        if self.include_ax:
            elements = merge_dom_and_ax(dom_elements, self._capture_ax_elements(region=region))
        else:
            elements = dom_elements
        viewport = payload.get("viewport_size")
        viewport_size = tuple(viewport) if viewport else None
        return SensorFrame(
            elements=elements,
            url=payload.get("url"),
            viewport_size=viewport_size,
            device_scale_factor=float(payload.get("device_scale_factor") or 1.0),
        )

    def screenshot(self, region: BBox | None = None) -> bytes:
        kwargs: dict[str, Any] = {}
        if region is not None:
            x, y, width, height = region
            kwargs["clip"] = {"x": x, "y": y, "width": width, "height": height}
        return self.page.screenshot(**kwargs)

    def _capture_ax_elements(self, region: BBox | None = None) -> list[Element]:
        accessibility = getattr(self.page, "accessibility", None)
        if accessibility is None or not hasattr(accessibility, "snapshot"):
            return []
        try:
            snapshot = accessibility.snapshot(interesting_only=True)
        except TypeError:
            snapshot = accessibility.snapshot()
        except Exception:
            return []
        if not snapshot:
            return []
        return list(_ax_nodes_to_elements(snapshot, region=region))


def merge_dom_and_ax(dom_elements: list[Element], ax_elements: list[Element]) -> list[Element]:
    merged = list(dom_elements)
    used_ax: set[int] = set()
    for dom_index, dom_element in enumerate(merged):
        match_index = _best_ax_match(dom_element, ax_elements, used_ax)
        if match_index is None:
            continue
        used_ax.add(match_index)
        merged[dom_index] = _merge_element_state(dom_element, ax_elements[match_index])

    for index, ax_element in enumerate(ax_elements):
        if index in used_ax:
            continue
        if ax_element.is_visible and (ax_element.text or ax_element.is_interactive):
            merged.append(ax_element)
    return merged


def _best_ax_match(dom_element: Element, ax_elements: list[Element], used_ax: set[int]) -> int | None:
    best_index: int | None = None
    best_score = 0
    for index, ax_element in enumerate(ax_elements):
        if index in used_ax:
            continue
        score = _ax_match_score(dom_element, ax_element)
        if score > best_score:
            best_index = index
            best_score = score
    if best_score >= 4:
        return best_index
    return None


def _ax_match_score(dom_element: Element, ax_element: Element) -> int:
    score = 0
    if dom_element.role == ax_element.role:
        score += 2
    if dom_element.text and ax_element.text and dom_element.text.casefold() == ax_element.text.casefold():
        score += 3
    elif dom_element.text and ax_element.text and (
        dom_element.text.casefold() in ax_element.text.casefold()
        or ax_element.text.casefold() in dom_element.text.casefold()
    ):
        score += 1
    if _bbox_close(dom_element.bbox, ax_element.bbox):
        score += 2
    return score


def _merge_element_state(dom_element: Element, ax_element: Element) -> Element:
    state = dict(dom_element.state)
    for key, value in ax_element.state.items():
        if key.startswith("ax_") or key in {"disabled", "focused", "checked", "selected", "expanded", "pressed"}:
            state.setdefault(key, value)
    state["ax_role"] = ax_element.role
    if ax_element.text:
        state["ax_name"] = ax_element.text
    return Element(
        id=dom_element.id,
        role=dom_element.role,
        text=dom_element.text or ax_element.text,
        bbox=dom_element.bbox,
        source=dom_element.source,
        state=state,
    )


def _ax_nodes_to_elements(node: dict[str, Any], *, region: BBox | None = None, path: str = "ax") -> list[Element]:
    elements: list[Element] = []
    role = normalize_role(node.get("role", ""))
    text = _ax_text(node)
    bbox = _ax_bbox(node)
    state = _ax_state(node, path)

    if role and role not in {"unknown", "webarea", "generic"} and (text or _ax_interactive(role, state)):
        if region is None or _intersects(bbox, region):
            elements.append(Element(id=0, role=role, text=text, bbox=bbox, source="ax", state=state))

    for ordinal, child in enumerate(node.get("children") or [], start=1):
        if isinstance(child, dict):
            elements.extend(_ax_nodes_to_elements(child, region=region, path=f"{path}>{role or 'node'}[{ordinal}]"))
    return elements


def _ax_text(node: dict[str, Any]) -> str:
    for key in ("name", "value", "description"):
        text = normalize_text(node.get(key))
        if text:
            return text
    return ""


def _ax_state(node: dict[str, Any], path: str) -> dict[str, object]:
    state: dict[str, object] = {"visible": True, "structural_path": path}
    role = normalize_role(node.get("role", ""))
    for key in ("disabled", "focused", "checked", "selected", "expanded", "pressed"):
        if key in node and node[key] is not None:
            state[key] = node[key]
            state[f"ax_{key}"] = node[key]
    if "value" in node and node["value"] not in {None, ""}:
        state["value"] = normalize_text(node["value"])
    if _ax_interactive(role, state):
        state["interactive"] = True
    return state


def _ax_interactive(role: str, state: dict[str, object]) -> bool:
    return role in {
        "button",
        "link",
        "textbox",
        "checkbox",
        "radio",
        "switch",
        "combobox",
        "menuitem",
        "tab",
        "slider",
        "spinbutton",
        "option",
    } or any(key in state for key in ("checked", "selected", "expanded", "pressed"))


def _ax_bbox(node: dict[str, Any]) -> BBox:
    for key in ("bbox", "bounds", "boundingBox"):
        value = node.get(key)
        if isinstance(value, dict):
            return (
                int(round(value.get("x", value.get("left", 0)) or 0)),
                int(round(value.get("y", value.get("top", 0)) or 0)),
                int(round(value.get("width", 0) or 0)),
                int(round(value.get("height", 0) or 0)),
            )
        if isinstance(value, (list, tuple)) and len(value) == 4:
            return (
                int(round(value[0])),
                int(round(value[1])),
                int(round(value[2])),
                int(round(value[3])),
            )
    return (0, 0, 0, 0)


def _bbox_close(left: BBox, right: BBox, tolerance: int = 6) -> bool:
    if left == (0, 0, 0, 0) or right == (0, 0, 0, 0):
        return False
    return all(abs(a - b) <= tolerance for a, b in zip(left, right))


def _intersects(a: BBox, b: BBox) -> bool:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return ax < bx + bw and ax + aw > bx and ay < by + bh and ay + ah > by


def _region_arg(region: BBox | None) -> dict[str, int] | None:
    if region is None:
        return None
    x, y, width, height = region
    return {"x": x, "y": y, "width": width, "height": height}
