from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from webapp.core.errors import AppError, ErrorCode
from webapp.core.models import Capability, DeviceInfo, OperationResult


@dataclass(frozen=True)
class ReplayFrame:
    path: Path
    expect: dict[str, Any] | None


@dataclass(frozen=True)
class ReplaySession:
    device_id: str
    name: str
    frames: tuple[ReplayFrame, ...]


class ReplayBackend:
    name = "replay"

    def __init__(self, sessions_dir: Path | str) -> None:
        self.sessions_dir = Path(sessions_dir).resolve()
        self._sessions: dict[str, ReplaySession] = {}
        self._indices: dict[str, int] = {}
        self._lock = threading.RLock()

    def capability(self) -> Capability:
        self._discover()
        if self._sessions:
            return Capability(name=self.name, available=True)
        return Capability(
            name=self.name,
            available=False,
            reason=f"No valid replay sessions found in {self.sessions_dir}.",
        )

    def list_devices(self) -> list[DeviceInfo]:
        self._discover()
        return [
            DeviceInfo(
                backend=self.name,
                device_id=session.device_id,
                name=session.name,
                status="device",
                source="replay-manifest",
                details={"frame_count": len(session.frames)},
            )
            for session in sorted(self._sessions.values(), key=lambda value: value.device_id)
        ]

    def snapshot(self, device_id: str) -> bytes:
        with self._lock:
            session = self._session(device_id)
            frame = session.frames[self._indices.setdefault(device_id, 0)]
            try:
                return frame.path.read_bytes()
            except OSError as exc:
                raise AppError(
                    ErrorCode.SNAPSHOT_FAILED,
                    "Replay frame could not be read.",
                    {"device_id": device_id, "path": str(frame.path)},
                ) from exc

    def tap(self, device_id: str, x: int, y: int) -> OperationResult:
        return self._apply_action(device_id, {"type": "tap", "x": x, "y": y})

    def swipe(
        self,
        device_id: str,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        duration_ms: int,
    ) -> OperationResult:
        return self._apply_action(
            device_id,
            {
                "type": "swipe",
                "x1": x1,
                "y1": y1,
                "x2": x2,
                "y2": y2,
                "duration_ms": duration_ms,
            },
        )

    def reset(self, device_id: str) -> None:
        with self._lock:
            self._session(device_id)
            self._indices[device_id] = 0

    def _apply_action(self, device_id: str, actual: dict[str, Any]) -> OperationResult:
        with self._lock:
            session = self._session(device_id)
            index = self._indices.setdefault(device_id, 0)
            expected = session.frames[index].expect
            mismatch = _action_mismatch(expected, actual)
            if mismatch is not None:
                raise AppError(
                    ErrorCode.REPLAY_ACTION_MISMATCH,
                    mismatch,
                    {
                        "device_id": device_id,
                        "frame_index": index,
                        "expected": expected,
                        "actual": actual,
                    },
                )
            next_index = min(index + 1, len(session.frames) - 1)
            self._indices[device_id] = next_index
            return OperationResult(
                ok=True,
                action=str(actual["type"]),
                message="Replay action accepted.",
                data={"frame_index": next_index},
            )

    def _session(self, device_id: str) -> ReplaySession:
        self._discover()
        session = self._sessions.get(device_id)
        if session is None:
            raise AppError(
                ErrorCode.REPLAY_SESSION_NOT_FOUND,
                "Replay session was not found.",
                {"device_id": device_id},
            )
        return session

    def _discover(self) -> None:
        with self._lock:
            sessions: dict[str, ReplaySession] = {}
            if self.sessions_dir.is_dir():
                for manifest in sorted(self.sessions_dir.glob("*/manifest.json")):
                    try:
                        session = _load_session(manifest)
                    except AppError:
                        continue
                    sessions[session.device_id] = session
            self._sessions = sessions
            self._indices = {
                device_id: min(self._indices.get(device_id, 0), len(session.frames) - 1)
                for device_id, session in sessions.items()
            }


def _load_session(manifest: Path) -> ReplaySession:
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise _invalid_manifest(manifest, "Manifest is not valid JSON.") from exc
    if not isinstance(payload, dict) or payload.get("version") != 1:
        raise _invalid_manifest(manifest, "Replay manifest version must be 1.")

    device_id = payload.get("device_id")
    raw_frames = payload.get("frames")
    if not isinstance(device_id, str) or not device_id.strip():
        raise _invalid_manifest(manifest, "Replay device_id must be a non-empty string.")
    if not isinstance(raw_frames, list) or not raw_frames:
        raise _invalid_manifest(manifest, "Replay frames must be a non-empty list.")

    session_dir = manifest.parent.resolve()
    frames: list[ReplayFrame] = []
    for index, raw_frame in enumerate(raw_frames):
        if not isinstance(raw_frame, dict) or not isinstance(raw_frame.get("file"), str):
            raise _invalid_manifest(manifest, f"Replay frame {index} has no file.")
        frame_path = (session_dir / raw_frame["file"]).resolve()
        if not _is_inside(frame_path, session_dir) or not frame_path.is_file():
            raise _invalid_manifest(manifest, f"Replay frame {index} is missing or unsafe.")
        expect = raw_frame.get("expect")
        if expect is not None and not isinstance(expect, dict):
            raise _invalid_manifest(manifest, f"Replay frame {index} expect must be an object.")
        frames.append(ReplayFrame(frame_path, expect))

    name = payload.get("name")
    return ReplaySession(
        device_id=device_id.strip(),
        name=name if isinstance(name, str) and name else device_id.strip(),
        frames=tuple(frames),
    )


def _action_mismatch(expected: dict[str, Any] | None, actual: dict[str, Any]) -> str | None:
    if expected is None:
        return "No action is expected for the current replay frame."
    if expected.get("type") != actual.get("type"):
        return f"Expected {expected.get('type')} but received {actual.get('type')}."

    tolerance = _non_negative_number(expected.get("tolerance"), 0.0)
    coordinate_keys = (
        ("x", "y") if actual["type"] == "tap" else ("x1", "y1", "x2", "y2")
    )
    for key in coordinate_keys:
        expected_value = expected.get(key)
        actual_value = actual.get(key)
        if not isinstance(expected_value, (int, float)):
            return f"Expected action has no numeric {key}."
        if abs(float(expected_value) - float(actual_value)) > tolerance:
            return f"Replay action coordinate {key} is outside tolerance."

    if actual["type"] == "swipe" and "duration_ms" in expected:
        duration_tolerance = _non_negative_number(expected.get("duration_tolerance_ms"), 0.0)
        expected_duration = expected["duration_ms"]
        if not isinstance(expected_duration, (int, float)):
            return "Expected swipe duration_ms is not numeric."
        if abs(float(expected_duration) - float(actual["duration_ms"])) > duration_tolerance:
            return "Replay swipe duration is outside tolerance."
    return None


def _non_negative_number(value: Any, default: float) -> float:
    if isinstance(value, (int, float)) and value >= 0:
        return float(value)
    return default


def _invalid_manifest(path: Path, message: str) -> AppError:
    return AppError(
        ErrorCode.REPLAY_MANIFEST_INVALID,
        message,
        {"path": str(path)},
    )


def _is_inside(path: Path, directory: Path) -> bool:
    try:
        path.relative_to(directory)
        return True
    except ValueError:
        return False
