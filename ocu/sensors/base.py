from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Protocol

from ..schema import BBox, Element


@dataclass(frozen=True, slots=True)
class SensorFrame:
    elements: list[Element]
    url: str | None = None
    viewport_size: tuple[int, int] | None = None
    device_scale_factor: float = 1.0


class Sensor(Protocol):
    def capture(self, region: BBox | None = None) -> SensorFrame:
        ...

    def screenshot(self, region: BBox | None = None) -> bytes:
        ...


def filter_region(elements: Iterable[Element], region: BBox | None) -> list[Element]:
    if region is None:
        return list(elements)
    return [element for element in elements if intersects(element.bbox, region)]


def intersects(a: BBox, b: BBox) -> bool:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return ax < bx + bw and ax + aw > bx and ay < by + bh and ay + ah > by
