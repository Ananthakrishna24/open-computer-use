from __future__ import annotations

from ..resolve import ResolvedTarget
from ..schema import Action


class XdotoolExecutor:
    def __init__(self, *args, **kwargs) -> None:
        raise NotImplementedError("XdotoolExecutor is planned for phase 2")

    def execute(self, action: Action, target: ResolvedTarget) -> None:
        raise NotImplementedError("XdotoolExecutor is planned for phase 2")
