import json
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from webapp.automation.battle import initialize_battle_settings
from webapp.devices.coordinates import FrameNormalizer
from webapp.devices.replay import ReplayBackend
from webapp.services.devices import DeviceService
from webapp.services.event_log import EventLog
from webapp.services.recognition import RecognitionService
from webapp.services.resources import ResourceService


class _Context:
    def __init__(self) -> None:
        self.events = []

    def emit(self, event_type, message, *, data=None, level="info"):
        self.events.append((event_type, message, data, level))

    def sleep(self, _seconds):
        return None


def _pattern(
    size: tuple[int, int],
    color: tuple[int, int, int],
    direction: str,
) -> Image.Image:
    image = Image.new("RGB", size, color)
    draw = ImageDraw.Draw(image)
    draw.rectangle((2, 2, size[0] - 3, size[1] - 3), outline=(245, 220, 70), width=2)
    if direction == "down":
        draw.line((3, 3, size[0] - 4, size[1] - 4), fill=(40, 220, 235), width=3)
    else:
        draw.line((3, size[1] - 4, size[0] - 4, 3), fill=(235, 70, 180), width=3)
    return image


def test_initialize_battle_settings_opens_menu_corrects_toggles_and_returns(tmp_path: Path):
    pytest.importorskip("cv2")
    assets = tmp_path / "assets"
    battle_assets = assets / "battle" / "CH"
    session = tmp_path / "replays" / "initialize"
    battle_assets.mkdir(parents=True)
    session.mkdir(parents=True)

    menu = _pattern((80, 50), (70, 80, 155), "down")
    enabled = _pattern((60, 58), (35, 155, 85), "down")
    disabled = _pattern((60, 58), (155, 55, 65), "up")
    back = _pattern((120, 50), (65, 95, 145), "up")
    speed_off = Image.new("RGB", (70, 43), (30, 45, 65))
    speed_off_draw = ImageDraw.Draw(speed_off)
    speed_off_draw.polygon((10, 5, 58, 21, 10, 37), fill=(75, 195, 235))
    np_auto = Image.new("RGB", (59, 77), (35, 50, 75))
    np_auto_draw = ImageDraw.Draw(np_auto)
    np_auto_draw.ellipse((7, 8, 51, 52), outline=(235, 185, 55), width=5)
    np_auto_draw.line((13, 65, 47, 65), fill=(225, 75, 155), width=5)
    menu.save(battle_assets / "fight_menu_button.png")
    enabled.save(battle_assets / "on.png")
    disabled.save(battle_assets / "off.png")
    speed_off.save(battle_assets / "speed_off.png")
    np_auto.save(battle_assets / "needSkip.png")
    back.save(battle_assets / "back.png")

    base = Image.new("RGB", (1280, 720), (18, 24, 32))
    menu_frame = base.copy()
    menu_frame.paste(menu, (1100, 20))
    toggle_frame = base.copy()
    toggle_frame.paste(disabled, (900, 300))
    toggle_frame.paste(disabled, (900, 400))
    toggle_frame.paste(enabled, (900, 500))
    toggle_frame.paste(speed_off, (700, 200))
    toggle_frame.paste(np_auto, (600, 180))
    back_frame = base.copy()
    back_frame.paste(back, (40, 30))
    frames = [
        menu_frame,
        toggle_frame,
        toggle_frame,
        toggle_frame,
        toggle_frame,
        toggle_frame,
        back_frame,
    ]
    expected = [
        {"type": "tap", "x": 1140, "y": 45},
        {"type": "tap", "x": 930, "y": 329},
        {"type": "tap", "x": 930, "y": 429},
        {"type": "tap", "x": 930, "y": 529},
        {"type": "tap", "x": 735, "y": 221},
        {"type": "tap", "x": 629, "y": 218},
        {"type": "tap", "x": 100, "y": 55},
    ]
    manifest_frames = []
    for index, (frame, action) in enumerate(zip(frames, expected, strict=True)):
        filename = f"{index}.png"
        frame.save(session / filename)
        manifest_frames.append({"file": filename, "expect": action})
    (session / "manifest.json").write_text(
        json.dumps(
            {"version": 1, "device_id": "initialize", "frames": manifest_frames}
        ),
        encoding="utf-8",
    )

    resources = ResourceService(assets, tmp_path / "data")
    devices = DeviceService(
        [ReplayBackend(tmp_path / "replays")],
        EventLog(),
        frame_normalizer=FrameNormalizer(),
    )
    devices.connect("replay", "initialize")

    result = initialize_battle_settings(
        _Context(),
        devices,
        RecognitionService(resources),
        "CH",
        action_wait_seconds=0,
    )

    assert result == {
        "changed": True,
        "states": [False, False, True],
        "speed_enabled": False,
        "np_skip_enabled": False,
        "actions": [
            "open_menu",
            "toggle_1",
            "toggle_2",
            "toggle_3",
            "enable_speed",
            "enable_np_skip",
            "close_menu",
        ],
    }
