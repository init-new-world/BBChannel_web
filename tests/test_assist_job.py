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


def test_assist_select_job_scrolls_before_retrying_recognition(tmp_path: Path):
    pytest.importorskip("cv2")
    assets = tmp_path / "assets"
    data = tmp_path / "data"
    session = tmp_path / "replays" / "assist-scroll"
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
    blank = Image.new("RGB", (1280, 720), (18, 24, 32))
    matched = blank.copy()
    matched.paste(portrait, (70, 225))
    blank.save(session / "0.png")
    matched.save(session / "1.png")
    (session / "manifest.json").write_text(
        json.dumps(
            {
                "version": 1,
                "device_id": "assist-scroll",
                "frames": [
                    {
                        "file": "0.png",
                        "expect": {
                            "type": "swipe",
                            "x1": 1120,
                            "y1": 620,
                            "x2": 1120,
                            "y2": 250,
                            "duration_ms": 500,
                        },
                    },
                    {
                        "file": "1.png",
                        "expect": {"type": "tap", "x": 370, "y": 195},
                    },
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
    devices.connect("replay", "assist-scroll")
    with JobManager(JobDatabase(tmp_path / "runtime.db")) as manager:
        register_assist_job(
            manager,
            ScriptDataService(data),
            devices,
            AssistRecognizer(resources, recognition),
        )
        job = manager.start(
            ASSIST_SELECT_JOB_KIND,
            {
                "setting_name": "assist",
                "max_scrolls": 1,
                "scroll_wait_seconds": 0,
                "tap_wait_seconds": 0,
            },
            device_key="replay:assist-scroll",
        )
        result = manager.wait(job.job_id, timeout=3)

    assert result.status == JobStatus.SUCCEEDED
    assert result.result["attempts"] == 2
    assert result.result["scrolls"] == 1
    assert result.result["selected"]["anchor"] == [100, 255]


def test_assist_select_job_refreshes_list_after_scroll_limit(tmp_path: Path):
    pytest.importorskip("cv2")
    assets = tmp_path / "assets"
    data = tmp_path / "data"
    session = tmp_path / "replays" / "assist-refresh"
    servant_faces = assets / "servantface"
    battle_assets = assets / "battle" / "CH"
    settings = data / "settings"
    servant_faces.mkdir(parents=True)
    battle_assets.mkdir(parents=True)
    settings.mkdir(parents=True)
    session.mkdir(parents=True)

    def pattern(size: tuple[int, int], color: tuple[int, int, int]) -> Image.Image:
        image = Image.new("RGB", size, color)
        draw = ImageDraw.Draw(image)
        draw.rectangle((2, 2, size[0] - 3, size[1] - 3), outline=(245, 220, 70), width=2)
        draw.line((3, size[1] - 4, size[0] - 4, 3), fill=(40, 220, 235), width=2)
        return image

    portrait = pattern((60, 60), (145, 65, 115))
    refresh_button = pattern((60, 30), (35, 110, 175))
    refresh_confirm = pattern((30, 20), (70, 145, 85))
    portrait.save(servant_faces / "Support_1.png")
    refresh_button.save(battle_assets / "listupdatebtn.png")
    refresh_confirm.save(battle_assets / "listupdate.png")
    blank = Image.new("RGB", (1280, 720), (18, 24, 32))
    refresh_screen = blank.copy()
    refresh_screen.paste(refresh_button, (1100, 50))
    confirm_screen = blank.copy()
    confirm_screen.paste(refresh_confirm, (600, 400))
    matched_screen = blank.copy()
    matched_screen.paste(portrait, (70, 225))
    for index, frame in enumerate((blank, refresh_screen, confirm_screen, matched_screen)):
        frame.save(session / f"{index}.png")
    (session / "manifest.json").write_text(
        json.dumps(
            {
                "version": 1,
                "device_id": "assist-refresh",
                "frames": [
                    {
                        "file": "0.png",
                        "expect": {
                            "type": "swipe",
                            "x1": 1120,
                            "y1": 620,
                            "x2": 1120,
                            "y2": 250,
                            "duration_ms": 500,
                        },
                    },
                    {
                        "file": "1.png",
                        "expect": {"type": "tap", "x": 1130, "y": 65},
                    },
                    {
                        "file": "2.png",
                        "expect": {"type": "tap", "x": 615, "y": 410},
                    },
                    {
                        "file": "3.png",
                        "expect": {"type": "tap", "x": 370, "y": 195},
                    },
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
    devices.connect("replay", "assist-refresh")
    with JobManager(JobDatabase(tmp_path / "runtime.db")) as manager:
        register_assist_job(
            manager,
            ScriptDataService(data),
            devices,
            AssistRecognizer(resources, recognition),
        )
        job = manager.start(
            ASSIST_SELECT_JOB_KIND,
            {
                "setting_name": "assist",
                "max_scrolls": 1,
                "max_refreshes": 1,
                "scroll_wait_seconds": 0,
                "refresh_wait_seconds": 0,
                "tap_wait_seconds": 0,
            },
            device_key="replay:assist-refresh",
        )
        result = manager.wait(job.job_id, timeout=3)

    assert result.status == JobStatus.SUCCEEDED
    assert result.result["attempts"] == 3
    assert result.result["scrolls"] == 1
    assert result.result["refreshes"] == 1
