import json
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from webapp.automation.assist import ASSIST_SELECT_JOB_KIND, register_assist_job
from webapp.devices.coordinates import FrameNormalizer
from webapp.devices.replay import ReplayBackend
from webapp.runtime import JobDatabase, JobManager, JobStatus
from webapp.services.assist import AssistRecognizer
from webapp.services.devices import DeviceService
from webapp.services.event_log import EventLog
from webapp.services.recognition import RecognitionService
from webapp.services.resources import ResourceService
from webapp.services.script_data import ScriptDataService


def test_assist_select_job_taps_first_matching_candidate(tmp_path: Path):
    pytest.importorskip("cv2")
    assets = tmp_path / "assets"
    data = tmp_path / "data"
    session = tmp_path / "replays" / "assist"
    servant_faces = assets / "servantface"
    settings = data / "settings"
    servant_faces.mkdir(parents=True)
    settings.mkdir(parents=True)
    session.mkdir(parents=True)

    portrait = Image.new("RGB", (60, 60), (40, 70, 100))
    portrait_draw = ImageDraw.Draw(portrait)
    portrait_draw.rectangle((7, 7, 52, 52), fill=(205, 90, 175))
    portrait_draw.line((5, 53, 54, 6), fill=(45, 225, 190), width=4)
    portrait.save(servant_faces / "Support_1.png")
    frame = Image.new("RGB", (1280, 720), (18, 24, 32))
    frame.paste(portrait, (70, 225))
    frame.save(session / "0.png")
    (session / "manifest.json").write_text(
        json.dumps(
            {
                "version": 1,
                "device_id": "assist",
                "frames": [
                    {
                        "file": "0.png",
                        "expect": {"type": "tap", "x": 370, "y": 195},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (data / "servant_info_CH.json").write_text(
        json.dumps({"Support": {"other_name": [], "SN": "314"}}),
        encoding="utf-8",
    )
    (settings / "assist.json").write_text(
        json.dumps(
            {
                "server": "CH",
                "servant_0_name": "Support",
                "assistIdx": 0,
                "assistMode": "从者礼装",
                "assistEquip": None,
                "fullEquip": 0,
                "onlyFriendAssist": 0,
                "NPlevel": 1,
                "skillsLevel": [0, 0, 0],
            }
        ),
        encoding="utf-8",
    )

    resources = ResourceService(assets, data)
    recognition = RecognitionService(resources)
    devices = DeviceService(
        [ReplayBackend(tmp_path / "replays")],
        EventLog(),
        frame_normalizer=FrameNormalizer(),
    )
    devices.connect("replay", "assist")
    with JobManager(JobDatabase(tmp_path / "runtime.db")) as manager:
        register_assist_job(
            manager,
            ScriptDataService(data),
            devices,
            AssistRecognizer(resources, recognition),
        )
        job = manager.start(
            ASSIST_SELECT_JOB_KIND,
            {"setting_name": "assist", "tap_wait_seconds": 0},
            device_key="replay:assist",
        )
        result = manager.wait(job.job_id, timeout=3)

    assert result.status == JobStatus.SUCCEEDED
    assert result.result["setting_name"] == "assist"
    assert result.result["attempts"] == 1
    assert result.result["scrolls"] == 0
    assert result.result["selected"]["anchor"] == [100, 255]
    assert result.result["selected"]["tap_point"] == [370, 195]
    assert result.result["tap"]["ok"] is True
