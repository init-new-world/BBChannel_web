import json
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from webapp.automation.entry import BATTLE_PREPARE_JOB_KIND, register_battle_entry_job
from webapp.devices.coordinates import FrameNormalizer
from webapp.devices.replay import ReplayBackend
from webapp.runtime import JobDatabase, JobManager, JobStatus
from webapp.services.devices import DeviceService
from webapp.services.event_log import EventLog
from webapp.services.recognition import RecognitionService
from webapp.services.resources import ResourceService
from webapp.services.script_data import ScriptDataService


def test_battle_prepare_job_confirms_team_starts_quest_and_waits_for_battle(tmp_path: Path):
    pytest.importorskip("cv2")
    assets = tmp_path / "assets"
    data = tmp_path / "data"
    session = tmp_path / "replays" / "prepare"
    battle_assets = assets / "battle" / "CH"
    settings = data / "settings"
    battle_assets.mkdir(parents=True)
    settings.mkdir(parents=True)
    session.mkdir(parents=True)

    def pattern(size: tuple[int, int], color: tuple[int, int, int]) -> Image.Image:
        image = Image.new("RGB", size, color)
        draw = ImageDraw.Draw(image)
        draw.rectangle((2, 2, size[0] - 3, size[1] - 3), outline=(245, 220, 70), width=2)
        draw.line((3, size[1] - 4, size[0] - 4, 3), fill=(40, 220, 235), width=2)
        return image

    team_decide = pattern((80, 40), (80, 65, 150))
    start_task = pattern((120, 45), (35, 120, 170))
    attack = pattern((90, 45), (150, 55, 80))
    team_decide.save(battle_assets / "teamDecide.png")
    start_task.save(battle_assets / "start_task.png")
    attack.save(battle_assets / "attack.png")
    base = Image.new("RGB", (1280, 720), (18, 24, 32))
    team_frame = base.copy()
    team_frame.paste(team_decide, (600, 500))
    start_frame = base.copy()
    start_frame.paste(start_task, (1050, 620))
    battle_frame = base.copy()
    battle_frame.paste(attack, (1100, 600))
    for index, frame in enumerate((team_frame, start_frame, battle_frame)):
        frame.save(session / f"{index}.png")
    (session / "manifest.json").write_text(
        json.dumps(
            {
                "version": 1,
                "device_id": "prepare",
                "frames": [
                    {
                        "file": "0.png",
                        "expect": {"type": "tap", "x": 640, "y": 520},
                    },
                    {
                        "file": "1.png",
                        "expect": {"type": "tap", "x": 1110, "y": 642},
                    },
                    {"file": "2.png"},
                ],
            }
        ),
        encoding="utf-8",
    )
    (data / "servant_info_CH.json").write_text("{}", encoding="utf-8")
    (settings / "prepare.json").write_text(
        json.dumps({"server": "CH"}),
        encoding="utf-8",
    )

    resources = ResourceService(assets, data)
    recognition = RecognitionService(resources)
    devices = DeviceService(
        [ReplayBackend(tmp_path / "replays")],
        EventLog(),
        frame_normalizer=FrameNormalizer(),
    )
    devices.connect("replay", "prepare")
    with JobManager(JobDatabase(tmp_path / "runtime.db")) as manager:
        register_battle_entry_job(
            manager,
            ScriptDataService(data),
            devices,
            recognition,
        )
        job = manager.start(
            BATTLE_PREPARE_JOB_KIND,
            {
                "setting_name": "prepare",
                "timeout_seconds": 2,
                "poll_interval": 0,
                "action_wait_seconds": 0,
            },
            device_key="replay:prepare",
        )
        result = manager.wait(job.job_id, timeout=3)

    assert result.status == JobStatus.SUCCEEDED
    assert result.result["setting_name"] == "prepare"
    assert result.result["ready"] is True
    assert result.result["actions"] == ["team_decide", "start_task"]
    assert result.result["attempts"] == 3
