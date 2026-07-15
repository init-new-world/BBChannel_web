import json
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from webapp.automation.completion import BATTLE_COMPLETE_JOB_KIND, register_completion_job
from webapp.devices.coordinates import FrameNormalizer
from webapp.devices.replay import ReplayBackend
from webapp.runtime import JobDatabase, JobManager, JobStatus
from webapp.services.devices import DeviceService
from webapp.services.event_log import EventLog
from webapp.services.recognition import RecognitionService
from webapp.services.resources import ResourceService
from webapp.services.script_data import ScriptDataService


def _pattern(size: tuple[int, int], color: tuple[int, int, int]) -> Image.Image:
    image = Image.new("RGB", size, color)
    draw = ImageDraw.Draw(image)
    draw.rectangle((2, 2, size[0] - 3, size[1] - 3), outline=(245, 220, 70), width=2)
    draw.line((3, size[1] - 4, size[0] - 4, 3), fill=(40, 220, 235), width=2)
    return image


def _run_completion(
    tmp_path: Path,
    frames: list[tuple[Image.Image, dict | None]],
    *,
    config: dict | None = None,
    payload: dict | None = None,
):
    assets = tmp_path / "assets"
    data = tmp_path / "data"
    session = tmp_path / "replays" / "completion"
    battle_assets = assets / "battle" / "CH"
    drop_assets = assets / "drop"
    settings = data / "settings"
    battle_assets.mkdir(parents=True)
    drop_assets.mkdir(parents=True)
    settings.mkdir(parents=True)
    session.mkdir(parents=True)

    next_button = _pattern((100, 40), (80, 65, 150))
    run_again = _pattern((120, 50), (35, 120, 170))
    friendship_max = _pattern((90, 45), (145, 75, 105))
    drop_item = _pattern((40, 40), (165, 105, 45))
    next_button.save(battle_assets / "next.png")
    run_again.save(battle_assets / "run_again.png")
    friendship_max.save(battle_assets / "jblevel10.png")
    drop_item.save(drop_assets / "item.png")
    manifest_frames = []
    for index, (frame, expected) in enumerate(frames):
        filename = f"{index}.png"
        frame.save(session / filename)
        entry = {"file": filename}
        if expected is not None:
            entry["expect"] = expected
        manifest_frames.append(entry)
    (session / "manifest.json").write_text(
        json.dumps(
            {"version": 1, "device_id": "completion", "frames": manifest_frames}
        ),
        encoding="utf-8",
    )
    (data / "servant_info_CH.json").write_text("{}", encoding="utf-8")
    (settings / "completion.json").write_text(
        json.dumps({"server": "CH", **(config or {})}),
        encoding="utf-8",
    )

    resources = ResourceService(assets, data)
    recognition = RecognitionService(resources)
    devices = DeviceService(
        [ReplayBackend(tmp_path / "replays")],
        EventLog(),
        frame_normalizer=FrameNormalizer(),
    )
    devices.connect("replay", "completion")
    with JobManager(JobDatabase(tmp_path / "runtime.db")) as manager:
        register_completion_job(
            manager,
            ScriptDataService(data),
            devices,
            recognition,
            resources,
        )
        job = manager.start(
            BATTLE_COMPLETE_JOB_KIND,
            {
                "setting_name": "completion",
                "timeout_seconds": 2,
                "poll_interval": 0,
                "action_wait_seconds": 0,
                **(payload or {}),
            },
            device_key="replay:completion",
        )
        return manager.wait(job.job_id, timeout=3)


def test_completion_advances_results_until_repeat_is_available(tmp_path: Path):
    pytest.importorskip("cv2")
    base = Image.new("RGB", (1280, 720), (18, 24, 32))
    next_frame = base.copy()
    next_frame.paste(_pattern((100, 40), (80, 65, 150)), (600, 500))
    repeat_frame = base.copy()
    repeat_frame.paste(_pattern((120, 50), (35, 120, 170)), (900, 600))

    result = _run_completion(
        tmp_path,
        [
            (next_frame, {"type": "tap", "x": 650, "y": 520}),
            (repeat_frame, None),
        ],
    )

    assert result.status == JobStatus.SUCCEEDED
    assert result.result["complete"] is True
    assert result.result["repeated"] is False
    assert result.result["actions"] == ["next"]
    assert result.result["attempts"] == 2


def test_completion_can_start_the_next_run(tmp_path: Path):
    pytest.importorskip("cv2")
    frame = Image.new("RGB", (1280, 720), (18, 24, 32))
    frame.paste(_pattern((120, 50), (35, 120, 170)), (900, 600))

    result = _run_completion(
        tmp_path,
        [(frame, {"type": "tap", "x": 960, "y": 625})],
        payload={"repeat": True},
    )

    assert result.status == JobStatus.SUCCEEDED
    assert result.result["complete"] is True
    assert result.result["repeated"] is True
    assert result.result["actions"] == ["run_again"]


def test_completion_stops_when_full_friendship_is_reached(tmp_path: Path):
    pytest.importorskip("cv2")
    frame = Image.new("RGB", (1280, 720), (18, 24, 32))
    frame.paste(_pattern((90, 45), (145, 75, 105)), (500, 350))

    result = _run_completion(
        tmp_path,
        [(frame, None)],
        config={"fullFriendshipStop": 1},
    )

    assert result.status == JobStatus.SUCCEEDED
    assert result.result["complete"] is False
    assert result.result["stopped"] is True
    assert result.result["reason"] == "full_friendship"
    assert result.result["actions"] == []


def test_completion_counts_configured_drops_and_stops_at_limit(tmp_path: Path):
    pytest.importorskip("cv2")
    frame = Image.new("RGB", (1280, 720), (18, 24, 32))
    drop_item = _pattern((40, 40), (165, 105, 45))
    frame.paste(drop_item, (300, 250))
    frame.paste(drop_item, (700, 450))

    result = _run_completion(
        tmp_path,
        [(frame, None)],
        config={
            "dropStopNum": 2,
            "dropImage": "E:/old/BBchannel/assets/drop/item.png",
        },
    )

    assert result.status == JobStatus.SUCCEEDED
    assert result.result["complete"] is False
    assert result.result["stopped"] is True
    assert result.result["reason"] == "drop_limit"
    assert result.result["drop_count"] == 2
