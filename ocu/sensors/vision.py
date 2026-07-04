from __future__ import annotations

from ..schema import BBox
from .base import SensorFrame


class VisionSensor:
    def __init__(self, *args, **kwargs) -> None:
        raise NotImplementedError("VisionSensor is planned for phase 3")

    def capture(self, region: BBox | None = None) -> SensorFrame:
        raise NotImplementedError("VisionSensor is planned for phase 3")

    def screenshot(self, region: BBox | None = None) -> bytes:
        raise NotImplementedError("VisionSensor is planned for phase 3")
