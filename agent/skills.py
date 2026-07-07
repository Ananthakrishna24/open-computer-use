from __future__ import annotations

import itertools
import json
import random
import time
from typing import Any

SHAPE_KINDS = {"box": "rectangle", "ellipse": "ellipse", "diamond": "diamond"}


def _element(kind: str, x: float, y: float, w: float, h: float, **extra: Any) -> dict[str, Any]:
    element = {
        "id": f"{kind}-{random.randrange(16**8):08x}",
        "type": kind,
        "x": float(x),
        "y": float(y),
        "width": float(w),
        "height": float(h),
        "angle": 0,
        "strokeColor": "#1e1e1e",
        "backgroundColor": "transparent",
        "fillStyle": "solid",
        "strokeWidth": 2,
        "strokeStyle": "solid",
        "roughness": 1,
        "opacity": 100,
        "groupIds": [],
        "frameId": None,
        "roundness": {"type": 3} if kind == "rectangle" else None,
        "seed": random.randrange(2**31),
        "version": 1,
        "versionNonce": random.randrange(2**31),
        "isDeleted": False,
        "boundElements": None,
        "updated": int(time.time() * 1000),
        "link": None,
        "locked": False,
    }
    element.update(extra)
    return element


def _wrap(label: str, width_chars: int) -> list[str]:
    lines = []
    for raw in label.split("\n"):
        line = ""
        for word in raw.split():
            candidate = f"{line} {word}".strip()
            if line and len(candidate) > width_chars:
                lines.append(line)
                line = word
            else:
                line = candidate
        lines.append(line)
    return lines


def _fit_label(label: str, w: float, h: float, size: float) -> tuple[str, float]:
    while True:
        budget = max(1, int((w - 24) / (size * 0.6)))
        lines = _wrap(label, budget)
        width = max(len(line) for line in lines) * size * 0.6
        height = len(lines) * size * 1.25
        if size <= 12 or (width <= w - 16 and height <= h - 8):
            return "\n".join(lines), size
        size -= 2


def _text(label: str, x: float, y: float, size: float, container: str | None = None) -> dict[str, Any]:
    lines = label.split("\n")
    width = max(len(line) for line in lines) * size * 0.6
    height = len(lines) * size * 1.25
    if container:
        x -= width / 2
        y -= height / 2
    return _element(
        "text",
        x,
        y,
        width,
        height,
        text=label,
        fontSize=size,
        fontFamily=1,
        textAlign="center" if container else "left",
        verticalAlign="middle" if container else "top",
        containerId=container,
        originalText=label,
        autoResize=True,
        lineHeight=1.25,
    )


def _shape(kind: str, spec: dict[str, Any]) -> list[dict[str, Any]]:
    x, y = float(spec["x"]), float(spec["y"])
    w, h = float(spec.get("w") or 200), float(spec.get("h") or 80)
    shape = _element(kind, x, y, w, h)
    label = str(spec.get("label") or "").replace("\\n", "\n").strip()
    if not label:
        return [shape]
    label, size = _fit_label(label, w, h, float(spec.get("size") or 20))
    text = _text(label, x + w / 2, y + h / 2, size, container=shape["id"])
    shape["boundElements"] = [{"id": text["id"], "type": "text"}]
    return [shape, text]


def _arrow(spec: dict[str, Any]) -> list[dict[str, Any]]:
    (x1, y1), (x2, y2) = spec["from"], spec["to"]
    arrow = _element(
        "arrow",
        float(x1),
        float(y1),
        abs(float(x2) - float(x1)),
        abs(float(y2) - float(y1)),
        points=[[0, 0], [float(x2) - float(x1), float(y2) - float(y1)]],
        lastCommittedPoint=None,
        startBinding=None,
        endBinding=None,
        startArrowhead=None,
        endArrowhead="arrow",
        elbowed=False,
    )
    arrow["roundness"] = {"type": 2}
    return [arrow]


def build_elements(specs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    elements: list[dict[str, Any]] = []
    for index, spec in enumerate(specs):
        kind = str(spec.get("kind") or "")
        try:
            if kind in SHAPE_KINDS:
                elements.extend(_shape(SHAPE_KINDS[kind], spec))
            elif kind == "text":
                label = str(spec["label"]).replace("\\n", "\n")
                elements.append(_text(label, float(spec["x"]), float(spec["y"]), float(spec.get("size") or 20)))
            elif kind == "arrow":
                elements.extend(_arrow(spec))
            else:
                raise ValueError(f"unknown kind {kind!r}")
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"element {index}: {exc}") from exc
    return elements


def layout_warnings(elements: list[dict[str, Any]]) -> list[str]:
    shapes = [e for e in elements if e["type"] in {"rectangle", "ellipse", "diamond"}]
    labels = {e["containerId"]: e for e in elements if e["type"] == "text" and e.get("containerId")}
    free_texts = [e for e in elements if e["type"] == "text" and not e.get("containerId")]

    def name(element: dict[str, Any]) -> str:
        text = labels.get(element["id"], element if element["type"] == "text" else None)
        return text["text"].splitlines()[0] if text else element["type"]

    warnings = []
    for shape in shapes:
        label = labels.get(shape["id"])
        if label and (label["width"] > shape["width"] - 16 or label["height"] > shape["height"] - 8):
            warnings.append(
                f"label {name(shape)!r} does not fit its shape even after shrinking; "
                f"enlarge the shape to ~{int(label['width'] + 40)}x{int(label['height'] + 30)} or shorten the label"
            )
    for a, b in itertools.combinations(shapes + free_texts, 2):
        if (
            a["x"] < b["x"] + b["width"]
            and b["x"] < a["x"] + a["width"]
            and a["y"] < b["y"] + b["height"]
            and b["y"] < a["y"] + a["height"]
        ):
            warnings.append(f"{name(a)!r} and {name(b)!r} overlap; move one of them")
    return warnings


def draw(agent: Any, args: dict[str, Any]) -> str:
    specs = args.get("elements") or []
    try:
        elements = build_elements(list(specs))
    except ValueError as exc:
        return f"error: {exc}"
    if not elements:
        return "error: elements list was empty"
    page = agent.env.page
    payload = json.dumps({"type": "excalidraw/clipboard", "elements": elements})
    try:
        if "excalidraw.com" not in page.url:
            page.goto("https://excalidraw.com/", wait_until="domcontentloaded")
            page.wait_for_timeout(1000)
        page.keyboard.press("Escape")
        page.keyboard.press("Control+a")
        page.keyboard.press("Delete")
        page.evaluate(
            "payload => {"
            "const data = new DataTransfer();"
            "data.setData('text/plain', payload);"
            "document.dispatchEvent(new ClipboardEvent('paste', {clipboardData: data}));"
            "}",
            payload,
        )
        page.wait_for_timeout(800)
        page.keyboard.press("Shift+1")
        page.keyboard.press("Escape")
        kept = page.evaluate(
            "() => JSON.parse(localStorage.getItem('excalidraw') || '[]').filter(e => !e.isDeleted).length"
        )
    except Exception as exc:
        return f"error: {exc}"
    if kept != len(elements):
        return f"warning: sent {len(elements)} elements but the canvas kept {kept}; some were dropped or the old drawing was not cleared"
    summary = f"did: canvas replaced with {len(specs)} shapes ({kept} elements), zoomed to fit"
    problems = layout_warnings(elements)
    if problems:
        summary += "".join("\nlayout: " + problem for problem in problems)
    return summary


DRAW_TOOL = {
    "type": "function",
    "function": {
        "name": "draw",
        "description": (
            "Excalidraw skill: replace the excalidraw.com canvas with a diagram built "
            "from simple element specs. Load the excalidraw skill first for usage."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "elements": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "properties": {
                            "kind": {"type": "string", "enum": ["box", "ellipse", "diamond", "text", "arrow"]},
                            "label": {"type": "string"},
                            "x": {"type": "number"},
                            "y": {"type": "number"},
                            "w": {"type": "number"},
                            "h": {"type": "number"},
                            "size": {"type": "number"},
                            "from": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 2},
                            "to": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 2},
                        },
                        "required": ["kind"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["elements"],
            "additionalProperties": False,
        },
    },
}

EXCALIDRAW_INSTRUCTIONS = (
    "excalidraw skill loaded. Never draw by clicking the canvas: the canvas is "
    "invisible to observations, so clicks cannot be verified. Use the draw tool.\n\n"
    "Call draw with the complete diagram; every call replaces the whole canvas. "
    "Element kinds:\n"
    '- {"kind": "box", "label": "Tokenizer", "x": 100, "y": 80, "w": 240, "h": 80} '
    "(also ellipse, diamond; label is centered inside)\n"
    '- {"kind": "text", "label": "Title", "x": 100, "y": 20, "size": 28}\n'
    '- {"kind": "arrow", "from": [220, 160], "to": [220, 240]}\n\n'
    "Layout: y grows downward. Stack flow diagrams top to bottom: boxes about "
    "240x80, gaps of 60-80px between them, arrows from the bottom edge of one box "
    "to the top edge of the next. Multi-line labels use \\n.\n\n"
    "The result reports how many elements the canvas kept and lists layout: problems "
    "(overlapping shapes, labels wider than their shape). If any appear, call draw "
    "again with the corrected full diagram. Only tell the user the drawing is done "
    "after a did: result with no layout: lines."
)

SKILLS: dict[str, dict[str, Any]] = {
    "excalidraw": {
        "description": "draw diagrams, flowcharts, or architecture sketches on excalidraw.com",
        "instructions": EXCALIDRAW_INSTRUCTIONS,
        "tools": [DRAW_TOOL],
        "handlers": {"draw": draw},
    },
}

SKILL_TOOL = {
    "type": "function",
    "function": {
        "name": "skill",
        "description": (
            "Load expert instructions and extra tools for a task type. Call this "
            "before attempting a task a skill covers. Available skills: "
            + "; ".join(f"{name} — {spec['description']}" for name, spec in SKILLS.items())
        ),
        "parameters": {
            "type": "object",
            "properties": {"name": {"type": "string", "enum": list(SKILLS)}},
            "required": ["name"],
            "additionalProperties": False,
        },
    },
}
