from __future__ import annotations

from typing import Protocol

from webapp.core.models import Capability, DeviceInfo, OperationResult


class DeviceBackend(Protocol):
    name: str

    def capability(self) -> Capability:
        ...

    def list_devices(self) -> list[DeviceInfo]:
        ...

    def snapshot(self, device_id: str) -> bytes:
        ...

    def tap(self, device_id: str, x: int, y: int) -> OperationResult:
        ...

    def swipe(
        self,
        device_id: str,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        duration_ms: int,
    ) -> OperationResult:
        ...
