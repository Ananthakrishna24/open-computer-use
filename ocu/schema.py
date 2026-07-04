from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

BBox = tuple[int, int, int, int]
Coordinate = tuple[int, int]

ACTION_VERBS = {
    "click",
    "type",
    "press",
    "scroll",
    "drag",
    "wait",
    "goto",
    "back",
    "observe",
    "done",
}

INTERACTIVE_ROLES = {
    "button",
    "link",
    "input",
    "textbox",
    "textarea",
    "searchbox",
    "checkbox",
    "radio",
    "switch",
    "combobox",
    "select",
    "menuitem",
    "tab",
    "slider",
    "spinbutton",
    "option",
}


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).replace("\u00a0", " ").split())


def normalize_role(value: Any) -> str:
    role = normalize_text(value).lower()
    return role or "unknown"


def normalize_bbox(value: Any) -> BBox:
    if value is None:
        return (0, 0, 0, 0)
    if len(value) != 4:
        raise ValueError(f"bbox must contain 4 values, got {value!r}")
    x, y, width, height = value
    return (int(round(x)), int(round(y)), int(round(width)), int(round(height)))


@dataclass(frozen=True, slots=True)
class Element:
    id: int
    role: str
    text: str = ""
    bbox: BBox = (0, 0, 0, 0)
    source: str = "dom"
    state: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", int(self.id))
        object.__setattr__(self, "role", normalize_role(self.role))
        object.__setattr__(self, "text", normalize_text(self.text))
        object.__setattr__(self, "bbox", normalize_bbox(self.bbox))
        object.__setattr__(self, "source", normalize_text(self.source).lower() or "unknown")
        object.__setattr__(self, "state", dict(self.state or {}))

    @property
    def center(self) -> Coordinate:
        x, y, width, height = self.bbox
        return (x + width // 2, y + height // 2)

    @property
    def is_interactive(self) -> bool:
        return self.role in INTERACTIVE_ROLES or bool(self.state.get("interactive"))

    @property
    def is_visible(self) -> bool:
        if self.state.get("visible") is False:
            return False
        _, _, width, height = self.bbox
        return width > 0 and height > 0

    def with_id(self, element_id: int) -> "Element":
        return Element(
            id=element_id,
            role=self.role,
            text=self.text,
            bbox=self.bbox,
            source=self.source,
            state=self.state,
        )


@dataclass(frozen=True, slots=True)
class Observation:
    frame: int
    kind: str
    text: str
    elements: dict[int, Element]
    tokens: int

    def __post_init__(self) -> None:
        if self.kind not in {"key", "delta"}:
            raise ValueError(f"Observation.kind must be 'key' or 'delta', got {self.kind!r}")
        object.__setattr__(self, "frame", int(self.frame))
        object.__setattr__(self, "tokens", int(self.tokens))
        object.__setattr__(self, "elements", dict(self.elements))


@dataclass(frozen=True, slots=True)
class Action:
    verb: str
    target: int | None = None
    coordinate: Coordinate | None = None
    text: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        verb = normalize_role(self.verb)
        if verb not in ACTION_VERBS:
            raise ValueError(f"unsupported action verb {self.verb!r}")
        object.__setattr__(self, "verb", verb)
        if self.target is not None:
            object.__setattr__(self, "target", int(self.target))
        if self.coordinate is not None:
            if len(self.coordinate) != 2:
                raise ValueError("coordinate must contain 2 values")
            x, y = self.coordinate
            object.__setattr__(self, "coordinate", (int(round(x)), int(round(y))))
        if self.text is not None:
            object.__setattr__(self, "text", str(self.text))
        object.__setattr__(self, "metadata", dict(self.metadata or {}))

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "Action":
        known = {
            "verb", "action", "target", "id", "element", "element_id",
            "coordinate", "text", "value", "url", "from", "start", "to", "end",
        }
        target = next(
            (value[key] for key in ("target", "id", "element", "element_id") if value.get(key) is not None),
            None,
        )
        coordinate = value.get("coordinate")
        if isinstance(target, (list, tuple)):
            if coordinate is None and len(target) == 2:
                coordinate = target
            target = None
        if coordinate is None:
            coordinate = next(
                (value[key] for key in ("from", "start") if value.get(key) is not None),
                None,
            )
        to = next((value[key] for key in ("to", "end") if value.get(key) is not None), None)
        if isinstance(coordinate, (list, tuple)) and len(coordinate) == 4:
            if to is None:
                to = list(coordinate[2:])
            coordinate = list(coordinate[:2])
        text = value.get("text")
        if text is None:
            text = value.get("value")
        if text is None:
            text = value.get("url")
        metadata = {k: v for k, v in value.items() if k not in known}
        if to is not None:
            metadata["to"] = to
        return cls(
            verb=value.get("verb") or value.get("action") or "",
            target=target,
            coordinate=coordinate,
            text=text,
            metadata=metadata,
        )

    @classmethod
    def coerce(cls, value: "Action | Mapping[str, Any]") -> "Action":
        if isinstance(value, Action):
            return value
        return cls.from_mapping(value)

    def label(self) -> str:
        if self.target is not None:
            target = f" [{self.target}]"
        elif self.coordinate is not None:
            target = f" {self.coordinate}"
        else:
            target = ""
        if self.text and self.verb in {"type", "press", "goto"}:
            return f"{self.verb}{target} {self.text!r}"
        return f"{self.verb}{target}"
