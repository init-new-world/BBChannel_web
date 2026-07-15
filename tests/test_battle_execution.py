import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

cv2 = pytest.importorskip("cv2")
np = pytest.importorskip("numpy")

from webapp.app import create_app
from webapp.automation.battle import register_battle_jobs
from webapp.devices.coordinates import FrameNormalizer
from webapp.devices.replay import ReplayBackend
from webapp.runtime import JobDatabase, JobManager, JobStatus
from webapp.services.devices import DeviceService
from webapp.services.event_log import EventLog
from webapp.services.cards import CommandCardRecognizer
from webapp.services.recognition import RecognitionService
from webapp.services.resources import ResourceService
from webapp.services.script_data import ScriptDataService


def _write_image(path: Path, image) -> None:
    assert cv2.imwrite(str(path), image)


def test_execute_skills_job_recognizes_battle_and_taps_skill_target(tmp_path: Path):
    assets = tmp_path / "assets"
    data = tmp_path / "data"
    session = tmp_path / "replays" / "skills"
    (assets / "battle" / "CH").mkdir(parents=True)
    (data / "settings").mkdir(parents=True)
    session.mkdir(parents=True)

    attack = np.zeros((28, 34, 3), dtype=np.uint8)
    attack[2:26, 2:32] = (30, 180, 240)
    attack[8:20, 12:22] = (255, 255, 255)
    frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    frame[560:588, 1100:1134] = attack
    _write_image(assets / "battle" / "CH" / "attack.png", attack)
    for index in range(3):
        _write_image(session / f"{index}.png", frame)

    (session / "manifest.json").write_text(
        json.dumps(
            {
                "version": 1,
                "device_id": "skills",
                "frames": [
                    {"file": "0.png", "expect": {"type": "tap", "x": 474, "y": 590}},
                    {"file": "1.png", "expect": {"type": "tap", "x": 640, "y": 440}},
                    {"file": "2.png"},
                ],
            }
        ),
        encoding="utf-8",
    )
    (data / "servant_info_CH.json").write_text(
        json.dumps({"Servant A": {"other_name": []}}),
        encoding="utf-8",
    )
    (data / "settings" / "demo.json").write_text(
        json.dumps(
            {
                "server": "CH",
                "servant_0_name": "Servant A",
                "round1_turns": 1,
                "round1_turn0_skill": [[5, 2]],
            }
        ),
        encoding="utf-8",
    )

    event_log = EventLog()
    devices = DeviceService(
        [ReplayBackend(tmp_path / "replays")],
        event_log,
        frame_normalizer=FrameNormalizer(),
    )
    devices.connect("replay", "skills")
    with JobManager(JobDatabase(tmp_path / "runtime.db")) as manager:
        app = create_app(
            assets,
            data,
            device_service=devices,
            event_log=event_log,
            job_manager=manager,
        )
        with TestClient(app) as client:
            response = client.post(
                "/api/jobs",
                json={
                    "kind": "battle.execute-skills",
                    "payload": {
                        "setting_name": "demo",
                        "timeout_seconds": 1,
                        "poll_interval": 0.01,
                        "tap_interval_seconds": 0,
                    },
                },
            )
            assert response.status_code == 202
            job_id = response.json()["job"]["job_id"]
            result = manager.wait(job_id, timeout=2)

    assert result.status == JobStatus.SUCCEEDED
    assert result.result == {
        "setting_name": "demo",
        "action_count": 1,
        "tap_count": 2,
    }
    events = manager.database.list_events(job_id)
    assert [event.data["role"] for event in events if event.event_type == "device_action"] == [
        "servant_skill_5",
        "skill_target_2",
    ]


def test_execute_skills_rejects_np_before_snapshot_or_tap(tmp_path: Path):
    data = tmp_path / "data"
    (data / "settings").mkdir(parents=True)
    (data / "servant_info_CH.json").write_text(
        json.dumps({"Servant A": {"other_name": []}}),
        encoding="utf-8",
    )
    (data / "settings" / "np.json").write_text(
        json.dumps(
            {
                "server": "CH",
                "servant_0_name": "Servant A",
                "round1_turns": 1,
                "round1_turn0_np": [1],
            }
        ),
        encoding="utf-8",
    )
    device_calls = []

    class NoActionDevice:
        def snapshot(self):
            device_calls.append("snapshot")
            raise AssertionError("snapshot must not be called")

        def tap(self, _x, _y):
            device_calls.append("tap")
            raise AssertionError("tap must not be called")

    with JobManager(JobDatabase(tmp_path / "runtime.db")) as manager:
        register_battle_jobs(
            manager,
            ScriptDataService(data),
            NoActionDevice(),
            object(),
        )
        job = manager.start(
            "battle.execute-skills",
            {"setting_name": "np"},
            device_key="replay:unused",
        )
        result = manager.wait(job.job_id, timeout=2)

    assert result.status == JobStatus.FAILED
    assert result.error["message"] == "Program contains non-skill actions."
    assert device_calls == []


def test_execute_battle_job_runs_skill_and_command_phase(tmp_path: Path):
    assets = tmp_path / "assets"
    data = tmp_path / "data"
    session = tmp_path / "replays" / "battle"
    (assets / "battle" / "CH").mkdir(parents=True)
    (data / "settings").mkdir(parents=True)
    session.mkdir(parents=True)

    attack = np.zeros((28, 34, 3), dtype=np.uint8)
    attack[2:26, 2:32] = (30, 180, 240)
    attack[8:20, 12:22] = (255, 255, 255)
    arts = np.zeros((30, 46, 3), dtype=np.uint8)
    arts[2:28, 2:44] = (200, 80, 30)
    arts[9:21, 10:36] = (255, 255, 255)
    battle_frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    battle_frame[560:588, 1100:1134] = attack
    command_frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    command_frame[470:500, 130:176] = arts
    _write_image(assets / "battle" / "CH" / "attack.png", attack)
    for card_type in ("Arts", "Buster", "Quick"):
        _write_image(assets / "battle" / "CH" / f"{card_type}.png", arts)
    expectations = [
        (battle_frame, {"type": "tap", "x": 70, "y": 590}),
        (battle_frame, {"type": "tap", "x": 1150, "y": 600}),
        (command_frame, {"type": "tap", "x": 500, "y": 110}),
        (command_frame, {"type": "tap", "x": 150, "y": 500}),
        (command_frame, {"type": "tap", "x": 375, "y": 500}),
        (command_frame, None),
    ]
    frames = []
    for index, (image, expect) in enumerate(expectations):
        filename = f"{index}.png"
        _write_image(session / filename, image)
        frame = {"file": filename}
        if expect is not None:
            frame["expect"] = expect
        frames.append(frame)
    (session / "manifest.json").write_text(
        json.dumps({"version": 1, "device_id": "battle", "frames": frames}),
        encoding="utf-8",
    )
    (data / "servant_info_CH.json").write_text(
        json.dumps({"Servant A": {"other_name": []}}),
        encoding="utf-8",
    )
    (data / "settings" / "battle.json").write_text(
        json.dumps(
            {
                "server": "CH",
                "servant_0_name": "Servant A",
                "round1_turns": 1,
                "round1_turn0_skill": [1],
                "round1_turn0_np": [1],
            }
        ),
        encoding="utf-8",
    )

    event_log = EventLog()
    devices = DeviceService(
        [ReplayBackend(tmp_path / "replays")],
        event_log,
        frame_normalizer=FrameNormalizer(),
    )
    devices.connect("replay", "battle")
    with JobManager(JobDatabase(tmp_path / "runtime.db")) as manager:
        register_battle_jobs(
            manager,
            ScriptDataService(data),
            devices,
            RecognitionService(ResourceService(assets, data)),
        )
        job = manager.start(
            "battle.execute-plan",
            {
                "setting_name": "battle",
                "timeout_seconds": 1,
                "poll_interval": 0.01,
                "tap_interval_seconds": 0,
            },
            device_key="replay:battle",
        )
        result = manager.wait(job.job_id, timeout=2)

    assert result.status == JobStatus.SUCCEEDED
    assert result.result == {
        "setting_name": "battle",
        "turn_count": 1,
        "action_count": 2,
        "tap_count": 5,
    }
    events = manager.database.list_events(job.job_id)
    assert [event.data["role"] for event in events if event.event_type == "device_action"] == [
        "servant_skill_1",
        "attack",
        "np_1",
        "face_card_1",
        "face_card_2",
    ]


def test_execute_battle_job_recognizes_and_selects_strategy_cards(tmp_path: Path):
    assets = tmp_path / "assets"
    data = tmp_path / "data"
    session = tmp_path / "replays" / "strategy"
    (assets / "battle" / "CH").mkdir(parents=True)
    (data / "settings").mkdir(parents=True)
    session.mkdir(parents=True)

    def pattern(width, height, color, marker):
        image = np.zeros((height, width, 4), dtype=np.uint8)
        image[2:-2, 2:-2, :3] = color
        image[2:-2, 2:-2, 3] = 255
        image[marker : marker + 2, 3:-3, :3] = 255
        image[marker : marker + 2, 3:-3, 3] = 255
        return image

    attack = pattern(34, 28, (30, 180, 240), 8)
    colors = {
        "Buster": pattern(34, 20, (40, 40, 210), 4),
        "Arts": pattern(34, 20, (220, 80, 40), 8),
        "Quick": pattern(34, 20, (80, 190, 40), 12),
    }
    portraits = {
        1: pattern(48, 48, (130, 40, 50), 5),
        2: pattern(48, 48, (100, 40, 100), 10),
        3: pattern(48, 48, (70, 40, 150), 15),
    }
    _write_image(assets / "battle" / "CH" / "attack.png", attack)
    for name, image in colors.items():
        _write_image(assets / "battle" / "CH" / f"{name}.png", image)
    for position, image in portraits.items():
        directory = assets / "commands_CH" / str(100 + position)
        directory.mkdir(parents=True)
        _write_image(directory / "card_servant_1.png", image)
    star_directory = assets / "battle" / "public" / "starNum"
    star_directory.mkdir(parents=True)
    star_templates = {}
    for number in range(10):
        image = np.zeros((39, 40), dtype=np.uint8)
        image[5:34, 5:35] = 20 + number * 15
        image[6:33, 6 + number * 2 : 8 + number * 2] = 240
        mask = np.zeros_like(image)
        mask[5:34, 5:35] = 255
        _write_image(star_directory / f"n{number}.png", image)
        _write_image(star_directory / f"n{number}mask.png", mask)
        star_templates[number] = image

    battle_frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    battle_frame[560:588, 1100:1134] = attack[:, :, :3]
    command_frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    expected_cards = [(1, "Buster"), (2, "Arts"), (1, "Arts"), (3, "Quick"), (2, "Buster")]
    for slot, (position, color_name) in enumerate(expected_cards):
        x = slot * 256
        color = colors[color_name]
        portrait = portraits[position]
        command_frame[420:440, x + 20 : x + 54] = color[:, :, :3]
        command_frame[500:548, x + 100 : x + 148] = portrait[:, :, :3]
    command_frame[353:392, 584:624] = np.repeat(
        star_templates[6][:, :, np.newaxis],
        3,
        axis=2,
    )

    expectations = [
        (battle_frame, {"type": "tap", "x": 1150, "y": 600}),
        (command_frame, {"type": "tap", "x": 500, "y": 110}),
        (command_frame, {"type": "tap", "x": 650, "y": 500}),
        (command_frame, {"type": "tap", "x": 1175, "y": 500}),
        (command_frame, None),
    ]
    frames = []
    for index, (image, expect) in enumerate(expectations):
        filename = f"{index}.png"
        _write_image(session / filename, image)
        frame = {"file": filename}
        if expect is not None:
            frame["expect"] = expect
        frames.append(frame)
    (session / "manifest.json").write_text(
        json.dumps({"version": 1, "device_id": "strategy", "frames": frames}),
        encoding="utf-8",
    )
    servants = {
        "One": {"other_name": [], "SN": "101"},
        "Two": {"other_name": [], "SN": "102"},
        "Three": {"other_name": [], "SN": "103"},
    }
    (data / "servant_info_CH.json").write_text(json.dumps(servants), encoding="utf-8")
    strategy = {
        "card1": {"type": 0, "cards": [1], "criticalStar": 0, "more_or_less": True},
        "card2": {"type": 1, "cards": ["1A"], "criticalStar": 5, "more_or_less": True},
        "card3": {"type": 1, "cards": ["2B"], "criticalStar": 0, "more_or_less": True},
        "breakpoint": [False, False],
        "colorFirst": True,
    }
    (data / "settings" / "strategy.json").write_text(
        json.dumps(
            {
                "server": "CH",
                "servant_0_name": "One",
                "servant_1_name": "Two",
                "servant_2_name": "Three",
                "usedServant": [0, 1, 2],
                "round1_turns": 1,
                "round1_turn0_strategy": [strategy],
            }
        ),
        encoding="utf-8",
    )

    resources = ResourceService(assets, data)
    recognition = RecognitionService(resources)
    cards = CommandCardRecognizer(resources, recognition)
    devices = DeviceService(
        [ReplayBackend(tmp_path / "replays")],
        EventLog(),
        frame_normalizer=FrameNormalizer(),
    )
    devices.connect("replay", "strategy")
    with JobManager(JobDatabase(tmp_path / "runtime.db")) as manager:
        register_battle_jobs(
            manager,
            ScriptDataService(data),
            devices,
            recognition,
            cards,
        )
        job = manager.start(
            "battle.execute-plan",
            {
                "setting_name": "strategy",
                "timeout_seconds": 1,
                "poll_interval": 0.01,
                "tap_interval_seconds": 0,
            },
            device_key="replay:strategy",
        )
        result = manager.wait(job.job_id, timeout=3)

    assert result.status == JobStatus.SUCCEEDED
    assert result.result == {
        "setting_name": "strategy",
        "turn_count": 1,
        "action_count": 1,
        "tap_count": 4,
    }
    events = manager.database.list_events(job.job_id)
    assert [event.data["role"] for event in events if event.event_type == "device_action"] == [
        "attack",
        "np_1",
        "face_card_3",
        "face_card_5",
    ]
