from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import blake2b
from typing import Iterable

from .schema import Element, normalize_text

INTERNAL_STATE_KEYS = {
    "backend_node_id",
    "css_path",
    "node_id",
    "node_ref",
    "path",
    "structural_path",
}


@dataclass(frozen=True, slots=True)
class DiffResult:
    added: list[Element] = field(default_factory=list)
    removed: list[Element] = field(default_factory=list)
    changed: list[tuple[Element, Element]] = field(default_factory=list)
    unchanged: list[Element] = field(default_factory=list)

    @property
    def changed_count(self) -> int:
        return len(self.added) + len(self.removed) + len(self.changed)

    def change_ratio(self, previous_count: int, current_count: int) -> float:
        denominator = max(previous_count, current_count, 1)
        return min(1.0, self.changed_count / denominator)


@dataclass(frozen=True, slots=True)
class FrameUpdate:
    frame: int
    kind: str
    elements: dict[int, Element]
    previous_elements: dict[int, Element]
    diff: DiffResult
    url: str | None = None
    previous_url: str | None = None
    reason: str = "delta"
    last_action: str | None = None
    aborted_step: int | None = None


class StateStore:
    def __init__(
        self,
        *,
        keyframe_interval: int = 10,
        change_threshold: float = 0.40,
        change_threshold_min_count: int = 6,
        grid_size: int = 96,
    ) -> None:
        if keyframe_interval < 1:
            raise ValueError("keyframe_interval must be >= 1")
        if not 0 < change_threshold <= 1:
            raise ValueError("change_threshold must be in (0, 1]")
        if grid_size < 1:
            raise ValueError("grid_size must be >= 1")
        if change_threshold_min_count < 1:
            raise ValueError("change_threshold_min_count must be >= 1")
        self.keyframe_interval = keyframe_interval
        self.change_threshold = change_threshold
        self.change_threshold_min_count = change_threshold_min_count
        self.grid_size = grid_size
        self._frame = 0
        self._next_id = 1
        self._id_by_identity: dict[str, int] = {}
        self._elements: dict[int, Element] = {}
        self._url: str | None = None

    @property
    def frame(self) -> int:
        return self._frame

    @property
    def elements(self) -> dict[int, Element]:
        return dict(self._elements)

    @property
    def url(self) -> str | None:
        return self._url

    def reset(self) -> None:
        self._frame = 0
        self._next_id = 1
        self._id_by_identity.clear()
        self._elements.clear()
        self._url = None

    def ingest(
        self,
        raw_elements: Iterable[Element],
        *,
        url: str | None = None,
        mode: str = "auto",
        last_action: str | None = None,
        aborted_step: int | None = None,
    ) -> FrameUpdate:
        previous = self._elements
        previous_url = self._url
        current_list = self._assign_ids(list(raw_elements))
        current = {element.id: element for element in current_list}
        diff = diff_elements(previous, current)
        next_frame = self._frame + 1
        kind, reason = self._select_kind(mode, next_frame, previous, current, diff, previous_url, url)

        self._frame = next_frame
        self._elements = current
        self._url = url

        return FrameUpdate(
            frame=next_frame,
            kind=kind,
            elements=current,
            previous_elements=previous,
            diff=diff,
            url=url,
            previous_url=previous_url,
            reason=reason,
            last_action=last_action,
            aborted_step=aborted_step,
        )

    def _assign_ids(self, elements: list[Element]) -> list[Element]:
        base_counts: dict[str, int] = {}
        assigned: list[Element] = []

        for element in elements:
            base = self._identity_base(element)
            ordinal = base_counts.get(base, 0) + 1
            base_counts[base] = ordinal
            identity = f"{base}#{ordinal}"
            element_id = self._id_by_identity.get(identity)
            if element_id is None:
                element_id = self._next_id
                self._next_id += 1
                self._id_by_identity[identity] = element_id
            assigned.append(element.with_id(element_id))

        return assigned

    def _identity_base(self, element: Element) -> str:
        text = normalize_text(element.text).casefold()[:32]
        structural_path = normalize_text(
            element.state.get("structural_path") or element.state.get("path") or element.state.get("css_path") or ""
        )
        x, y, _, _ = element.bbox
        grid_cell = f"{x // self.grid_size}:{y // self.grid_size}"
        material = "\x1f".join([element.role, text, structural_path, grid_cell])
        digest = blake2b(material.encode("utf-8"), digest_size=12).hexdigest()
        return digest

    def _select_kind(
        self,
        mode: str,
        frame: int,
        previous: dict[int, Element],
        current: dict[int, Element],
        diff: DiffResult,
        previous_url: str | None,
        url: str | None,
    ) -> tuple[str, str]:
        normalized_mode = mode.lower()
        if normalized_mode in {"full", "key", "keyframe", "region"}:
            return "key", "requested"
        if normalized_mode == "delta" and previous:
            return "delta", "requested"
        if not previous:
            return "key", "first_observation"
        if previous_url and url and previous_url != url:
            return "key", "url_changed"
        if frame % self.keyframe_interval == 0:
            return "key", "interval"
        if (
            diff.changed_count >= self.change_threshold_min_count
            and diff.change_ratio(len(previous), len(current)) > self.change_threshold
        ):
            return "key", "change_threshold"
        return "delta", "delta"


def diff_elements(previous: dict[int, Element], current: dict[int, Element]) -> DiffResult:
    added: list[Element] = []
    removed: list[Element] = []
    changed: list[tuple[Element, Element]] = []
    unchanged: list[Element] = []

    previous_ids = set(previous)
    current_ids = set(current)
    for element_id in sorted(current_ids - previous_ids):
        added.append(current[element_id])
    for element_id in sorted(previous_ids - current_ids):
        removed.append(previous[element_id])
    for element_id in sorted(previous_ids & current_ids):
        old = previous[element_id]
        new = current[element_id]
        if element_changed(old, new):
            changed.append((old, new))
        else:
            unchanged.append(new)

    return DiffResult(added=added, removed=removed, changed=changed, unchanged=unchanged)


def element_changed(old: Element, new: Element) -> bool:
    if old.role != new.role or old.text != new.text or old.source != new.source:
        return True
    if bbox_changed(old.bbox, new.bbox):
        return True
    return _public_state(old) != _public_state(new)


def bbox_changed(old: tuple[int, int, int, int], new: tuple[int, int, int, int], tolerance: int = 3) -> bool:
    return any(abs(left - right) > tolerance for left, right in zip(old, new))


def _public_state(element: Element) -> dict[str, object]:
    return {key: value for key, value in element.state.items() if key not in INTERNAL_STATE_KEYS}
