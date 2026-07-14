import json
from pathlib import Path

import pytest

from webapp.core.errors import AppError, ErrorCode
from webapp.devices.replay import ReplayBackend


def _session(root: Path, frames: list[dict], *, device_id: str = "recording-1") -> Path:
    session = root / device_id
    session.mkdir(parents=True)
    for index in range(len(frames)):
        (session / f"{index}.png").write_bytes(f"frame-{index}".encode())
    payload = {
        "version": 1,
        "device_id": device_id,
        "name": "Recorded battle",
        "frames": [
            {"file": f"{index}.png", **frame}
            for index, frame in enumerate(frames)
        ],
    }
    (session / "manifest.json").write_text(json.dumps(payload), encoding="utf-8")
    return session


def test_replay_backend_lists_sessions_and_returns_current_frame(tmp_path: Path):
    _session(tmp_path, [{"expect": {"type": "tap", "x": 100, "y": 200}}, {}])
    backend = ReplayBackend(tmp_path)

    assert backend.capability().available is True
    assert backend.list_devices()[0].details == {"frame_count": 2}
    assert backend.snapshot("recording-1") == b"frame-0"


def test_replay_backend_accepts_expected_tap_and_advances_frame(tmp_path: Path):
    _session(
        tmp_path,
        [{"expect": {"type": "tap", "x": 100, "y": 200, "tolerance": 3}}, {}],
    )
    backend = ReplayBackend(tmp_path)

    result = backend.tap("recording-1", 102, 198)

    assert result.ok is True
    assert result.data == {"frame_index": 1}
    assert backend.snapshot("recording-1") == b"frame-1"
    backend.reset("recording-1")
    assert backend.snapshot("recording-1") == b"frame-0"


def test_replay_backend_rejects_mismatched_action_without_advancing(tmp_path: Path):
    _session(tmp_path, [{"expect": {"type": "tap", "x": 100, "y": 200}}, {}])
    backend = ReplayBackend(tmp_path)

    with pytest.raises(AppError) as exc_info:
        backend.tap("recording-1", 101, 200)

    assert exc_info.value.code == ErrorCode.REPLAY_ACTION_MISMATCH
    assert backend.snapshot("recording-1") == b"frame-0"


def test_replay_backend_validates_swipe_duration(tmp_path: Path):
    _session(
        tmp_path,
        [
            {
                "expect": {
                    "type": "swipe",
                    "x1": 10,
                    "y1": 20,
                    "x2": 30,
                    "y2": 40,
                    "duration_ms": 300,
                    "duration_tolerance_ms": 20,
                }
            },
            {},
        ],
    )
    backend = ReplayBackend(tmp_path)

    assert backend.swipe("recording-1", 10, 20, 30, 40, 315).ok is True


def test_replay_backend_skips_invalid_or_unsafe_manifest(tmp_path: Path):
    session = tmp_path / "unsafe"
    session.mkdir()
    (session / "manifest.json").write_text(
        json.dumps(
            {
                "version": 1,
                "device_id": "unsafe",
                "frames": [{"file": "../outside.png"}],
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "outside.png").write_bytes(b"outside")
    backend = ReplayBackend(tmp_path)

    assert backend.capability().available is False
    assert backend.list_devices() == []
