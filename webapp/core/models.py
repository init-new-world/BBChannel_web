from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class Capability:
    name: str
    available: bool
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DeviceInfo:
    backend: str
    device_id: str
    name: str | None = None
    status: str = "device"
    source: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ConnectionState:
    connected: bool
    backend: str | None = None
    device_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class OperationResult:
    ok: bool
    action: str
    message: str = ""
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MatchResult:
    template_path: str
    matched: bool
    confidence: float
    threshold: float
    top_left: list[int]
    size: list[int]
    center: list[int]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
