from __future__ import annotations

from ..schema import BBox
from .base import SensorFrame


class AxLinuxSensor:
    def __init__(self, *args, **kwargs) -> None:
        raise NotImplementedError("AxLinuxSensor is planned for phase 2")

    def capture(self, region: BBox | None = None) -> SensorFrame:
        raise NotImplementedError("AxLinuxSensor is planned for phase 2")

    def screenshot(self, region: BBox | None = None) -> bytes:
        raise NotImplementedError("AxLinuxSensor is planned for phase 2")
