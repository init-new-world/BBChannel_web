from __future__ import annotations

from io import BytesIO
import json
from pathlib import Path
from typing import Any

import pytest
from PIL import Image, ImageDraw

from webapp.automation.battle import create_battle_execute_plan_handler
from webapp.runtime import JobDatabase, JobManager, JobStatus
from webapp.services.battle_servants import (
    BATTLE_CLASS_ICON_RECTS_1080,
    STATUS_RECTS_1080,
    FrontlineServantRecognizer,
)
from webapp.services.cards import CommandCardRecognizer
from webapp.services.recognition import RecognitionService
from webapp.services.resources import ResourceService
from webapp.services.script_data import ScriptDataService


def _png_bytes(image: Image.Image) -> bytes:
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _class_icon(seed: int) -> Image.Image:
    image = Image.new("L", (125, 100), 20)
    draw = ImageDraw.Draw(image)
    draw.rectangle((8, 8, 116, 91), outline=230, width=3)
    draw.ellipse((15 + seed * 6, 15, 70 + seed * 6, 80), fill=90 + seed * 20)
    draw.line((10, 90 - seed * 7, 114, 12 + seed * 5), fill=245, width=4)
    return image


def _status_tile(seed: int) -> Image.Image:
    image = Image.new("RGB", (50, 55), (25 + seed * 15, 40, 90))
    draw = ImageDraw.Draw(image)
    draw.rectangle((3, 3, 46, 51), outline=(240, 220, 120), width=2)
    draw.rectangle((7, 10 + seed * 3, 21, 44), fill=(210, 70 + seed * 20, 60))
    draw.ellipse((27, 12, 43, 36 + seed * 2), fill=(60, 190, 220 - seed * 15))
    draw.line((5, 48, 44, 8 + seed * 4), fill=(255, 255, 255), width=2)
    return image


def _paste_scaled_box(
    canvas: Image.Image,
    tile: Image.Image,
    box_1080: tuple[int, int, int, int],
) -> None:
    width, height = canvas.size
    box_w_1080 = box_1080[2] - box_1080[0]
    box_h_1080 = box_1080[3] - box_1080[1]
    left = round(box_1080[0] * width / 1920)
    top = round(box_1080[1] * height / 1080)
    right = round(box_1080[2] * width / 1920)
    bottom = round(box_1080[3] * height / 1080)
    if tile.size == (125, 100) and (box_w_1080, box_h_1080) == (155, 155):
        region_1080 = Image.new("RGB", (155, 155), (15, 20, 28))
        region_1080.paste(tile.convert("RGB"), (15, 25))
        resized = region_1080.resize((right - left, bottom - top), Image.Resampling.BILINEAR)
    else:
        resized = tile.convert("RGB").resize((right - left, bottom - top), Image.Resampling.BILINEAR)
    canvas.paste(resized, (left, top))


def test_frontline_servant_recognizer_matches_classes_full_and_half_tiles_and_fallback(
    tmp_path: Path,
) -> None:
    pytest.importorskip("cv2")
    assets = tmp_path / "assets"
    data = tmp_path / "data"
    class_dir = assets / "battle" / "public" / "classIcon"
    status_dir = assets / "status"
    class_dir.mkdir(parents=True)
    status_dir.mkdir(parents=True)
    data.mkdir(parents=True)

    saber_icon = _class_icon(1)
    caster_icon = _class_icon(2)
    lancer_icon = _class_icon(3)
    saber_icon.save(class_dir / "Saber.png")
    caster_icon.save(class_dir / "Caster.png")
    lancer_icon.save(class_dir / "Lancer.png")

    artoria_tile = _status_tile(1)
    castoria_tile = _status_tile(2)
    merlin_tile = _status_tile(3)

    saber_sheet = Image.new("RGB", (500, 110), (10, 10, 10))
    saber_sheet.paste(artoria_tile, (0, 0))
    saber_sheet.save(status_dir / "Saber.png")

    caster_sheet = Image.new("RGB", (500, 110), (10, 10, 10))
    caster_sheet.paste(castoria_tile, (50, 0))
    caster_sheet.paste(merlin_tile, (100, 0))
    caster_sheet.save(status_dir / "Caster.png")

    lancer_sheet = Image.new("RGB", (500, 110), (10, 10, 10))
    lancer_sheet.paste(_status_tile(4), (0, 0))
    lancer_sheet.save(status_dir / "Lancer.png")

    (status_dir / "status_info.json").write_text(
        json.dumps(
            {
                "Saber": ["阿尔托莉雅·潘德拉贡"],
                "Caster": ["诸葛孔明〔埃尔梅罗Ⅱ世〕", "阿尔托莉雅·卡斯特", "梅林"],
                "Lancer": ["库·丘林"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (data / "servant_info_CH.json").write_text(
        json.dumps(
            {
                "阿尔托莉雅·潘德拉贡": {"SN": "2", "other_name": ["呆毛王"]},
                "阿尔托莉雅·卡斯特": {"SN": "284", "other_name": ["C呆"]},
                "梅林": {"SN": "150", "other_name": []},
                "堂吉诃德": {"SN": "346", "other_name": []},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    screenshot = Image.new("RGB", (1280, 720), (15, 20, 28))
    _paste_scaled_box(screenshot, saber_icon, BATTLE_CLASS_ICON_RECTS_1080[0])
    _paste_scaled_box(screenshot, caster_icon, BATTLE_CLASS_ICON_RECTS_1080[1])
    _paste_scaled_box(screenshot, lancer_icon, BATTLE_CLASS_ICON_RECTS_1080[2])

    # Slot 1: full portrait tile match
    _paste_scaled_box(screenshot, artoria_tile, STATUS_RECTS_1080[0])

    # Slot 2: left half of portrait is occluded so only the right 25x55 half-tile matches
    occluded_castoria = castoria_tile.copy()
    ImageDraw.Draw(occluded_castoria).rectangle((0, 0, 23, 54), fill=(0, 0, 0))
    _paste_scaled_box(screenshot, occluded_castoria, STATUS_RECTS_1080[1])

    # Slot 3: unrecognized Lancer portrait that falls back to '堂吉诃德' on final_attempt
    unrecognized_lancer = Image.new("RGB", (50, 55), (80, 80, 80))
    draw_unrec = ImageDraw.Draw(unrecognized_lancer)
    for y in range(4, 52, 8):
        draw_unrec.line((4, y, 45, y), fill=(240, 240, 240), width=2)
    _paste_scaled_box(screenshot, unrecognized_lancer, STATUS_RECTS_1080[2])

    resources = ResourceService(assets, data)
    recognizer = FrontlineServantRecognizer(resources)
    raw = _png_bytes(screenshot)

    classes = recognizer.recognize_classes(raw)
    assert classes == ["Saber", "Caster", "Lancer"]

    first_pass = recognizer.recognize_names(raw, classes=classes, final_attempt=False)
    assert first_pass["complete"] is False
    assert first_pass["names"] == [
        "阿尔托莉雅·潘德拉贡",
        "阿尔托莉雅·卡斯特",
        None,
    ]

    final_pass = recognizer.recognize_names(
        raw,
        classes=classes,
        threshold=0.5,
        final_attempt=True,
    )
    assert final_pass["complete"] is True
    assert final_pass["names"] == [
        "阿尔托莉雅·潘德拉贡",
        "阿尔托莉雅·卡斯特",
        "堂吉诃德",
    ]

    servant_positions: list[dict[str, Any] | None] = [
        {"slot": 0, "name": "呆毛王", "sn": "2"},
        {"slot": 1, "name": None, "sn": None, "is_assist": True},
        {"slot": 2, "name": "梅林", "sn": "150"},
    ]
    occupied_positions: list[int | None] = [0, 1, 2, 3, 4, 5]
    party_servants = [
        {"slot": 0, "name": "呆毛王", "sn": "2", "aliases": ["阿尔托莉雅·潘德拉贡"]},
        {"slot": 1, "name": None, "sn": None, "is_assist": True},
        {"slot": 2, "name": "梅林", "sn": "150"},
    ]
    changed = recognizer.apply_recognized_names(
        final_pass["names"],
        servant_positions,
        occupied_positions=occupied_positions,
        party_servants=party_servants,
        server="CH",
    )
    assert changed is True
    assert servant_positions[0]["sn"] == "2"
    assert servant_positions[1]["sn"] == "284"
    assert servant_positions[1]["is_assist"] is True
    assert servant_positions[2]["sn"] == "346"
    assert servant_positions[2]["name"] == "堂吉诃德"


def test_battle_execute_plan_recovers_unrecognized_command_cards_via_frontline_servant_check(
    tmp_path: Path,
    monkeypatch,
) -> None:
    pytest.importorskip("cv2")
    assets = tmp_path / "assets"
    data = tmp_path / "data"
    (assets / "battle" / "CH").mkdir(parents=True)
    (assets / "battle" / "public" / "classIcon").mkdir(parents=True)
    (assets / "battle" / "public" / "starNum").mkdir(parents=True)
    (assets / "status").mkdir(parents=True)
    (data / "settings").mkdir(parents=True)

    attack = Image.new("RGB", (34, 28), (30, 180, 240))
    ImageDraw.Draw(attack).rectangle((8, 6, 25, 21), fill=(255, 255, 255))
    attack.save(assets / "battle" / "CH" / "attack.png")

    colors = {}
    for idx, (name, rgb) in enumerate(
        (("Buster", (210, 40, 40)), ("Arts", (40, 80, 220)), ("Quick", (40, 190, 80))),
        start=1,
    ):
        img = Image.new("RGB", (34, 20), rgb)
        ImageDraw.Draw(img).line((3 * idx, 2, 30, 17), fill=(255, 255, 255), width=2)
        img.save(assets / "battle" / "CH" / f"{name}.png")
        colors[name] = img

    for blocker_name, seed in (("freeze", 1), ("bjfy", 2)):
        blocker = Image.new("RGB", (20, 28), (180, 140 - seed * 40, 60))
        ImageDraw.Draw(blocker).line((2, 2 + seed * 3, 17, 25), fill=(255, 255, 255), width=2)
        blocker.save(assets / "battle" / "CH" / f"{blocker_name}.png")

    for number in range(10):
        star = Image.new("L", (40, 39), 0)
        ImageDraw.Draw(star).rectangle((5, 5, 34, 33), fill=20 + number * 15)
        star.save(assets / "battle" / "public" / "starNum" / f"n{number}.png")
        mask = Image.new("L", (40, 39), 0)
        ImageDraw.Draw(mask).rectangle((5, 5, 34, 33), fill=255)
        mask.save(assets / "battle" / "public" / "starNum" / f"n{number}mask.png")

    portraits = {}
    for idx, sn in enumerate(("101", "102", "103"), start=1):
        folder = assets / "commands_CH" / sn
        folder.mkdir(parents=True)
        portrait = Image.new("RGB", (48, 48), (20, 25, 35))
        draw_p = ImageDraw.Draw(portrait)
        if idx == 1:
            draw_p.rectangle((6, 6, 41, 20), fill=(240, 240, 240))
        elif idx == 2:
            draw_p.rectangle((6, 26, 20, 41), fill=(240, 240, 240))
        else:
            draw_p.ellipse((22, 22, 42, 42), outline=(240, 240, 240), width=4)
        portrait.save(folder / "card_servant_1.png")
        portraits[sn] = portrait

    saber_icon = _class_icon(1)
    caster_icon = _class_icon(2)
    berserker_icon = _class_icon(3)
    saber_icon.save(assets / "battle" / "public" / "classIcon" / "Saber.png")
    caster_icon.save(assets / "battle" / "public" / "classIcon" / "Caster.png")
    berserker_icon.save(assets / "battle" / "public" / "classIcon" / "Berserker.png")

    one_tile = _status_tile(1)
    two_tile = _status_tile(2)
    three_tile = _status_tile(3)
    for class_name, tile in (
        ("Saber", one_tile),
        ("Caster", two_tile),
        ("Berserker", three_tile),
    ):
        sheet = Image.new("RGB", (500, 110), (10, 10, 10))
        sheet.paste(tile, (0, 0))
        sheet.save(assets / "status" / f"{class_name}.png")

    (assets / "status" / "status_info.json").write_text(
        json.dumps(
            {
                "Saber": ["One"],
                "Caster": ["Two"],
                "Berserker": ["Three"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (data / "servant_info_CH.json").write_text(
        json.dumps(
            {
                "One": {"SN": "101", "other_name": []},
                "Two": {"SN": "102", "other_name": []},
                "Three": {"SN": "103", "other_name": []},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    # Slot 2 in the setting is initially configured as Two (102), but on the actual battle
    # field Three (103) is standing in slot 3, causing initial command card recognition to fail
    # until recovery backs out and runs checkServantName().
    (data / "settings" / "recovery.json").write_text(
        json.dumps(
            {
                "server": "CH",
                "no_speedup_skill": True,
                "interval_before_choose_card": 0,
                "servant_0_name": "One",
                "servant_1_name": "Two",
                "servant_2_name": "Two",
                "servant_3_name": "Three",
                "usedServant": [0, 1, 2, 3],
                "round1_turns": 1,
                "round1_turn0_strategy": [
                    {
                        "card1": {"type": 1, "cards": ["3B"], "criticalStar": 0, "more_or_less": True},
                        "card2": {"type": 1, "cards": ["1A"], "criticalStar": 0, "more_or_less": True},
                        "card3": {"type": 1, "cards": ["2Q"], "criticalStar": 0, "more_or_less": True},
                        "breakpoint": [False, False],
                        "colorFirst": True,
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    battle_screen = Image.new("RGB", (1280, 720), (18, 22, 30))
    battle_screen.paste(attack, (1100, 560))
    _paste_scaled_box(battle_screen, saber_icon, BATTLE_CLASS_ICON_RECTS_1080[0])
    _paste_scaled_box(battle_screen, caster_icon, BATTLE_CLASS_ICON_RECTS_1080[1])
    _paste_scaled_box(battle_screen, berserker_icon, BATTLE_CLASS_ICON_RECTS_1080[2])
    _paste_scaled_box(battle_screen, one_tile, STATUS_RECTS_1080[0])
    _paste_scaled_box(battle_screen, two_tile, STATUS_RECTS_1080[1])
    _paste_scaled_box(battle_screen, three_tile, STATUS_RECTS_1080[2])

    command_screen = Image.new("RGB", (1280, 720), (18, 22, 30))
    hand = [
        ("101", "Arts"),
        ("102", "Quick"),
        ("103", "Buster"),
        ("101", "Buster"),
        ("102", "Arts"),
    ]
    for slot_index, (sn, color_name) in enumerate(hand):
        x = slot_index * 256
        command_screen.paste(colors[color_name], (x + 20, 420))
        command_screen.paste(portraits[sn], (x + 100, 500))

    battle_bytes = _png_bytes(battle_screen)
    command_bytes = _png_bytes(command_screen)

    class _FakeDevice:
        def __init__(self) -> None:
            self.in_cards = False
            self.taps: list[tuple[int, int]] = []

        def snapshot(self) -> bytes:
            return command_bytes if self.in_cards else battle_bytes

        def tap(self, x: int, y: int):
            self.taps.append((x, y))
            if (x, y) == (1150, 600):
                self.in_cards = True
            elif (x, y) == (1201, 683):
                self.in_cards = False

            class _Op:
                def to_dict(self) -> dict[str, Any]:
                    return {"type": "tap", "x": x, "y": y}

            return _Op()

    device = _FakeDevice()
    resources = ResourceService(assets, data)
    recognition = RecognitionService(resources)
    card_recognizer = CommandCardRecognizer(resources, recognition)
    frontline_recognizer = FrontlineServantRecognizer(resources)

    monkeypatch.setattr(
        "webapp.automation.battle._wait_for_battle_transition",
        lambda *_args, **_kwargs: {"state": "finished", "round": None},
    )

    with JobManager(JobDatabase(tmp_path / "runtime.db")) as manager:
        manager.register(
            "battle.execute-plan",
            create_battle_execute_plan_handler(
                ScriptDataService(data),
                device,  # type: ignore[arg-type]
                recognition,
                card_recognizer,
                frontline_recognizer=frontline_recognizer,
            ),
            requires_device=True,
        )
        job = manager.start(
            "battle.execute-plan",
            {
                "setting_name": "recovery",
                "timeout_seconds": 2,
                "poll_interval": 0.01,
                "tap_interval_seconds": 0,
            },
            device_key="fake:recovery",
        )
        result = manager.wait(job.job_id, timeout=15)
        events = manager.database.list_events(job.job_id)

    assert result.status == JobStatus.SUCCEEDED, result.error
    # Attack -> Back (recovery) -> Attack (recovery) -> Card 3 (3B) -> Card 1 (1A) -> Card 2 (2Q)
    assert device.taps == [
        (1150, 600),
        (1201, 683),
        (1150, 600),
        (650, 500),
        (150, 500),
        (375, 500),
    ]
    event_types = [event.event_type for event in events]
    assert "frontline_servants" in event_types
    assert "card_recognition_recovery" in event_types


def test_battle_extra_turn_falls_back_to_default_cards_when_frontline_servant_diff_detected(
    tmp_path: Path,
    monkeypatch,
) -> None:
    pytest.importorskip("cv2")
    assets = tmp_path / "assets"
    data = tmp_path / "data"
    (assets / "battle" / "CH").mkdir(parents=True)
    (assets / "battle" / "public" / "classIcon").mkdir(parents=True)
    (assets / "battle" / "public" / "starNum").mkdir(parents=True)
    (assets / "status").mkdir(parents=True)
    (data / "settings").mkdir(parents=True)

    attack = Image.new("RGB", (34, 28), (30, 180, 240))
    ImageDraw.Draw(attack).rectangle((8, 6, 25, 21), fill=(255, 255, 255))
    attack.save(assets / "battle" / "CH" / "attack.png")

    colors = {}
    for idx, (name, rgb) in enumerate(
        (("Buster", (210, 40, 40)), ("Arts", (40, 80, 220)), ("Quick", (40, 190, 80))),
        start=1,
    ):
        img = Image.new("RGB", (34, 20), rgb)
        ImageDraw.Draw(img).line((3 * idx, 2, 30, 17), fill=(255, 255, 255), width=2)
        img.save(assets / "battle" / "CH" / f"{name}.png")
        colors[name] = img

    for blocker_name, seed in (("freeze", 1), ("bjfy", 2)):
        blocker = Image.new("RGB", (20, 28), (180, 140 - seed * 40, 60))
        ImageDraw.Draw(blocker).line((2, 2 + seed * 3, 17, 25), fill=(255, 255, 255), width=2)
        blocker.save(assets / "battle" / "CH" / f"{blocker_name}.png")

    for number in range(10):
        star = Image.new("L", (40, 39), 0)
        ImageDraw.Draw(star).rectangle((5, 5, 34, 33), fill=20 + number * 15)
        star.save(assets / "battle" / "public" / "starNum" / f"n{number}.png")
        mask = Image.new("L", (40, 39), 0)
        ImageDraw.Draw(mask).rectangle((5, 5, 34, 33), fill=255)
        mask.save(assets / "battle" / "public" / "starNum" / f"n{number}mask.png")

    portraits = {}
    for idx, sn in enumerate(("101", "102", "103"), start=1):
        folder = assets / "commands_CH" / sn
        folder.mkdir(parents=True)
        portrait = Image.new("RGB", (48, 48), (20, 25, 35))
        draw_p = ImageDraw.Draw(portrait)
        if idx == 1:
            draw_p.rectangle((6, 6, 41, 20), fill=(240, 240, 240))
        elif idx == 2:
            draw_p.rectangle((6, 26, 20, 41), fill=(240, 240, 240))
        else:
            draw_p.ellipse((22, 22, 42, 42), outline=(240, 240, 240), width=4)
        portrait.save(folder / "card_servant_1.png")
        portraits[sn] = portrait

    saber_icon = _class_icon(1)
    caster_icon = _class_icon(2)
    berserker_icon = _class_icon(3)
    saber_icon.save(assets / "battle" / "public" / "classIcon" / "Saber.png")
    caster_icon.save(assets / "battle" / "public" / "classIcon" / "Caster.png")
    berserker_icon.save(assets / "battle" / "public" / "classIcon" / "Berserker.png")

    one_tile = _status_tile(1)
    two_tile = _status_tile(2)
    three_tile = _status_tile(3)
    for class_name, tile in (
        ("Saber", one_tile),
        ("Caster", two_tile),
        ("Berserker", three_tile),
    ):
        sheet = Image.new("RGB", (500, 110), (10, 10, 10))
        sheet.paste(tile, (0, 0))
        sheet.save(assets / "status" / f"{class_name}.png")

    (assets / "status" / "status_info.json").write_text(
        json.dumps(
            {
                "Saber": ["One"],
                "Caster": ["Two"],
                "Berserker": ["Three"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (data / "servant_info_CH.json").write_text(
        json.dumps(
            {
                "One": {"SN": "101", "other_name": []},
                "Two": {"SN": "102", "other_name": []},
                "Three": {"SN": "103", "other_name": []},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    # Extra strategy demands an impossible card combination (`1Q` x3 when no Quick cards exist),
    # which would raise StrategySelectionError unless checkServantDiff falls back to default cards!
    (data / "settings" / "extra_diff.json").write_text(
        json.dumps(
            {
                "server": "CH",
                "no_speedup_skill": True,
                "interval_before_choose_card": 0,
                "servant_0_name": "One",
                "servant_1_name": "Two",
                "servant_2_name": "Two",
                "servant_3_name": "Three",
                "usedServant": [0, 1, 2, 3],
                "round1_turns": 1,
                "round1_extraStrategy": [
                    {
                        "card1": {"type": 1, "cards": ["1Q"], "criticalStar": 0, "more_or_less": True},
                        "card2": {"type": 1, "cards": ["1Q"], "criticalStar": 0, "more_or_less": True},
                        "card3": {"type": 1, "cards": ["1Q"], "criticalStar": 0, "more_or_less": True},
                        "breakpoint": [False, False],
                        "colorFirst": True,
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    battle_screen = Image.new("RGB", (1280, 720), (18, 22, 30))
    battle_screen.paste(attack, (1100, 560))
    _paste_scaled_box(battle_screen, saber_icon, BATTLE_CLASS_ICON_RECTS_1080[0])
    _paste_scaled_box(battle_screen, caster_icon, BATTLE_CLASS_ICON_RECTS_1080[1])
    _paste_scaled_box(battle_screen, berserker_icon, BATTLE_CLASS_ICON_RECTS_1080[2])
    _paste_scaled_box(battle_screen, one_tile, STATUS_RECTS_1080[0])
    _paste_scaled_box(battle_screen, two_tile, STATUS_RECTS_1080[1])
    _paste_scaled_box(battle_screen, three_tile, STATUS_RECTS_1080[2])

    command_screen = Image.new("RGB", (1280, 720), (18, 22, 30))
    hand = [
        ("101", "Buster"),
        ("102", "Arts"),
        ("103", "Buster"),
        ("101", "Arts"),
        ("102", "Buster"),
    ]
    for slot_index, (sn, color_name) in enumerate(hand):
        x = slot_index * 256
        command_screen.paste(colors[color_name], (x + 20, 420))
        command_screen.paste(portraits[sn], (x + 100, 500))

    battle_bytes = _png_bytes(battle_screen)
    command_bytes = _png_bytes(command_screen)

    class _FakeDevice:
        def __init__(self) -> None:
            self.in_cards = False
            self.taps: list[tuple[int, int]] = []

        def snapshot(self) -> bytes:
            return command_bytes if self.in_cards else battle_bytes

        def tap(self, x: int, y: int):
            self.taps.append((x, y))
            if (x, y) == (1150, 600):
                self.in_cards = True
            elif y == 500 and len([t for t in self.taps if t[1] == 500]) % 3 == 0:
                self.in_cards = False

            class _Op:
                def to_dict(self) -> dict[str, Any]:
                    return {"type": "tap", "x": x, "y": y}

            return _Op()

    transitions = iter(
        [
            {"state": "battle", "round": 1},
            {"state": "finished", "round": None},
        ]
    )
    monkeypatch.setattr(
        "webapp.automation.battle._wait_for_battle_transition",
        lambda *_args, **_kwargs: next(transitions),
    )

    device = _FakeDevice()
    resources = ResourceService(assets, data)
    recognition = RecognitionService(resources)
    card_recognizer = CommandCardRecognizer(resources, recognition)
    frontline_recognizer = FrontlineServantRecognizer(resources)

    with JobManager(JobDatabase(tmp_path / "runtime.db")) as manager:
        manager.register(
            "battle.execute-plan",
            create_battle_execute_plan_handler(
                ScriptDataService(data),
                device,  # type: ignore[arg-type]
                recognition,
                card_recognizer,
                frontline_recognizer=frontline_recognizer,
            ),
            requires_device=True,
        )
        job = manager.start(
            "battle.execute-plan",
            {
                "setting_name": "extra_diff",
                "timeout_seconds": 2,
                "poll_interval": 0.01,
                "tap_interval_seconds": 0,
            },
            device_key="fake:extra_diff",
        )
        result = manager.wait(job.job_id, timeout=15)
        events = manager.database.list_events(job.job_id)

    assert result.status == JobStatus.SUCCEEDED, result.error
    event_types = [event.event_type for event in events]
    assert "servant_diff" in event_types
    strategy_events = [
        event.data for event in events if event.event_type == "strategy_selection"
    ]
    assert strategy_events
    assert [item["slot"] for item in strategy_events[-1]["selected"]] == [1, 3, 5]


def test_build_autonomous_and_complex_skill_commands_filter_availability_and_unopened_skills() -> None:
    from webapp.automation.program import (
        build_autonomous_skill_commands,
        build_complex_skill_commands,
    )

    available = [True, False, True, True, False, False, False, True, True]
    unopened = [set(), {0}, {2}, set(), set(), set()]
    free_commands = build_autonomous_skill_commands(
        ["阿尔托莉雅·潘德拉贡", "诸葛孔明〔埃尔梅罗Ⅱ世〕", "库库尔坎", "", "", ""],
        [0, 1, 2, 3, 4, 5],
        default_target=2,
        available_skills=available,
        unopened_skills=unopened,
    )
    # Skill 1 (index 0, slot 0, rem 0) -> [1, 2]
    # Skill 2 (index 1) -> unavailable
    # Skill 3 (index 2, slot 0, rem 2) -> [3, 2]
    # Skill 4 (index 3, slot 1, rem 0) -> unopened in slot 1 ({0}) -> skipped
    # Skill 8 (index 7, slot 2, rem 1, Kukulkan) -> ["Kukulkan", 8, 1, 2]
    # Skill 9 (index 8, slot 2, rem 2) -> unopened in slot 2 ({2}) -> skipped
    assert free_commands == [
        [1, 2],
        [3, 2],
        ["Kukulkan", 8, 1, 2],
    ]

    complex_commands = build_complex_skill_commands(
        [5, [10, 1], ["Kukulkan", 7, 0]],
        free_commands,
        default_target=2,
    )
    assert complex_commands == [
        [5, 2],
        [10, 1],
        ["Kukulkan", 7, 0],
        [1, 2],
        [3, 2],
        ["Kukulkan", 8, 1, 2],
    ]


def test_battle_extra_turn_synthesizes_complex_skills_and_tracks_buffs_np_and_unopened_skills(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from webapp.automation.battle import (
        SKILL_NOT_AVAILABLE_ROI,
        _skill_cooldown_roi,
        create_battle_execute_plan_handler,
    )
    from webapp.runtime import JobDatabase, JobManager, JobStatus
    from webapp.services.cards import CommandCardRecognizer
    from webapp.services.recognition import RecognitionService
    from webapp.services.script_data import ScriptDataService

    pytest.importorskip("cv2")
    assets = tmp_path / "assets"
    data = tmp_path / "data"
    (assets / "battle" / "CH").mkdir(parents=True)
    (assets / "battle" / "public" / "classIcon").mkdir(parents=True)
    (assets / "battle" / "public" / "starNum").mkdir(parents=True)
    (assets / "status").mkdir(parents=True)
    (data / "settings").mkdir(parents=True)

    attack = Image.new("RGB", (34, 28), (30, 180, 240))
    ImageDraw.Draw(attack).rectangle((8, 6, 25, 21), fill=(255, 255, 255))
    attack.save(assets / "battle" / "CH" / "attack.png")

    colors: dict[str, Image.Image] = {}
    for idx, (name, rgb) in enumerate(
        (("Buster", (210, 40, 40)), ("Arts", (40, 80, 220)), ("Quick", (40, 190, 80))),
        start=1,
    ):
        img = Image.new("RGB", (34, 20), rgb)
        ImageDraw.Draw(img).line((3 * idx, 2, 30, 17), fill=(255, 255, 255), width=2)
        img.save(assets / "battle" / "CH" / f"{name}.png")
        colors[name] = img

    for blocker_name, seed in (("freeze", 1), ("bjfy", 2)):
        blocker = Image.new("RGB", (20, 28), (180, 140 - seed * 40, 60))
        ImageDraw.Draw(blocker).line((2, 2 + seed * 3, 17, 25), fill=(255, 255, 255), width=2)
        blocker.save(assets / "battle" / "CH" / f"{blocker_name}.png")

    for number in range(10):
        star = Image.new("L", (40, 39), 0)
        ImageDraw.Draw(star).rectangle((5, 5, 34, 33), fill=20 + number * 15)
        star.save(assets / "battle" / "public" / "starNum" / f"n{number}.png")
        mask = Image.new("L", (40, 39), 0)
        ImageDraw.Draw(mask).rectangle((5, 5, 34, 33), fill=255)
        mask.save(assets / "battle" / "public" / "starNum" / f"n{number}mask.png")

    incd = Image.new("RGB", (20, 20), (35, 35, 35))
    ImageDraw.Draw(incd).rectangle((4, 4, 15, 15), fill=(240, 200, 60))
    incd.save(assets / "battle" / "CH" / "incd1.png")

    not_avail = Image.new("RGB", (80, 32), (40, 20, 20))
    ImageDraw.Draw(not_avail).ellipse((10, 6, 70, 26), fill=(250, 120, 90))
    not_avail.save(assets / "battle" / "CH" / "notAvailable.png")

    portraits: dict[str, Image.Image] = {}
    for idx, sn in enumerate(("101", "102", "103"), start=1):
        folder = assets / "commands_CH" / sn
        folder.mkdir(parents=True, exist_ok=True)
        portrait = Image.new("RGB", (48, 48), (20, 25, 35))
        draw_p = ImageDraw.Draw(portrait)
        if idx == 1:
            draw_p.rectangle((6, 6, 41, 20), fill=(240, 240, 240))
        elif idx == 2:
            draw_p.rectangle((6, 26, 20, 41), fill=(240, 240, 240))
        else:
            draw_p.ellipse((22, 22, 42, 42), outline=(240, 240, 240), width=4)
        portrait.save(folder / "card_servant_1.png")
        portraits[sn] = portrait

    saber_icon = _class_icon(1)
    caster_icon = _class_icon(2)
    berserker_icon = _class_icon(3)
    saber_icon.save(assets / "battle" / "public" / "classIcon" / "Saber.png")
    caster_icon.save(assets / "battle" / "public" / "classIcon" / "Caster.png")
    berserker_icon.save(assets / "battle" / "public" / "classIcon" / "Berserker.png")

    one_tile = _status_tile(1)
    two_tile = _status_tile(2)
    three_tile = _status_tile(3)
    for class_name, tile in (
        ("Saber", one_tile),
        ("Caster", two_tile),
        ("Berserker", three_tile),
    ):
        sheet = Image.new("RGB", (500, 110), (10, 10, 10))
        sheet.paste(tile, (0, 0))
        sheet.save(assets / "status" / f"{class_name}.png")

    (assets / "status" / "status_info.json").write_text(
        json.dumps(
            {
                "Saber": ["One"],
                "Caster": ["Two"],
                "Berserker": ["Three"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (data / "servant_info_CH.json").write_text(
        json.dumps(
            {
                "One": {"SN": "101", "other_name": []},
                "Two": {"SN": "102", "other_name": []},
                "Three": {"SN": "103", "other_name": []},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (data / "settings" / "complex_diff.json").write_text(
        json.dumps(
            {
                "server": "CH",
                "no_speedup_skill": True,
                "interval_before_choose_card": 0,
                "servant_0_name": "One",
                "servant_1_name": "Two",
                "servant_2_name": "Two",
                "servant_3_name": "Three",
                "usedServant": [0, 1, 2, 3],
                "round1_turns": 1,
                "round1_turn0_skill": [[1, 2], 4],
                "round1_turn0_np": [2],
                "round1_extraSkill": [5],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    battle_screen = Image.new("RGB", (1280, 720), (18, 22, 30))
    battle_screen.paste(attack, (1100, 560))
    _paste_scaled_box(battle_screen, saber_icon, BATTLE_CLASS_ICON_RECTS_1080[0])
    _paste_scaled_box(battle_screen, caster_icon, BATTLE_CLASS_ICON_RECTS_1080[1])
    _paste_scaled_box(battle_screen, berserker_icon, BATTLE_CLASS_ICON_RECTS_1080[2])
    _paste_scaled_box(battle_screen, one_tile, STATUS_RECTS_1080[0])
    _paste_scaled_box(battle_screen, two_tile, STATUS_RECTS_1080[1])
    _paste_scaled_box(battle_screen, three_tile, STATUS_RECTS_1080[2])
    for cd_skill in (2, 3, 5, 6, 7, 9):
        roi_x, roi_y, _, _ = _skill_cooldown_roi(cd_skill, "CH")
        battle_screen.paste(incd, (roi_x + 4, roi_y + 4))

    popup_screen = Image.new("RGB", (1280, 720), (18, 22, 30))
    popup_screen.paste(
        not_avail,
        (SKILL_NOT_AVAILABLE_ROI[0] + 20, SKILL_NOT_AVAILABLE_ROI[1] + 10),
    )

    command_screen = Image.new("RGB", (1280, 720), (18, 22, 30))
    hand = [
        ("101", "Buster"),
        ("102", "Arts"),
        ("103", "Buster"),
        ("101", "Arts"),
        ("102", "Buster"),
    ]
    for slot_index, (sn, color_name) in enumerate(hand):
        x = slot_index * 256
        command_screen.paste(colors[color_name], (x + 20, 420))
        command_screen.paste(portraits[sn], (x + 100, 500))

    battle_bytes = _png_bytes(battle_screen)
    popup_bytes = _png_bytes(popup_screen)
    command_bytes = _png_bytes(command_screen)

    class _FakeDevice:
        def __init__(self) -> None:
            self.in_cards = False
            self.show_not_avail = False
            self.taps: list[tuple[int, int]] = []

        def snapshot(self) -> bytes:
            if self.show_not_avail:
                return popup_bytes
            return command_bytes if self.in_cards else battle_bytes

        def tap(self, x: int, y: int):
            self.taps.append((x, y))
            if (x, y) == (382, 590):
                self.show_not_avail = True
            elif (x, y) == (642, 563):
                self.show_not_avail = False
            elif (x, y) == (1150, 600):
                self.in_cards = True
            elif y == 500 and len([t for t in self.taps if t[1] == 500]) >= 2:
                self.in_cards = False

            class _Op:
                def to_dict(self) -> dict[str, Any]:
                    return {"type": "tap", "x": x, "y": y}

            return _Op()

    transitions = iter(
        [
            {"state": "battle", "round": 1},
            {"state": "finished", "round": None},
        ]
    )
    monkeypatch.setattr(
        "webapp.automation.battle._wait_for_battle_transition",
        lambda *_args, **_kwargs: next(transitions),
    )

    device = _FakeDevice()
    resources = ResourceService(assets, data)
    recognition = RecognitionService(resources)
    card_recognizer = CommandCardRecognizer(resources, recognition)
    frontline_recognizer = FrontlineServantRecognizer(resources)

    with JobManager(JobDatabase(tmp_path / "runtime.db")) as manager:
        manager.register(
            "battle.execute-plan",
            create_battle_execute_plan_handler(
                ScriptDataService(data),
                device,  # type: ignore[arg-type]
                recognition,
                card_recognizer,
                frontline_recognizer=frontline_recognizer,
            ),
            requires_device=True,
        )
        job = manager.start(
            "battle.execute-plan",
            {
                "setting_name": "complex_diff",
                "timeout_seconds": 2,
                "poll_interval": 0.01,
                "tap_interval_seconds": 0,
            },
            device_key="fake:complex_diff",
        )
        result = manager.wait(job.job_id, timeout=15)
        events = manager.database.list_events(job.job_id)

    assert result.status == JobStatus.SUCCEEDED, result.error
    diff_skill_events = [
        event.data for event in events if event.event_type == "servant_diff_skills"
    ]
    assert len(diff_skill_events) == 1
    assert diff_skill_events[0]["mode"] == "complex"
    # Slot 1 (frontline position 2) received buff [1, 2] and NP 2 -> highest buff score, so target is 2!
    assert diff_skill_events[0]["target"] == 2
    # Skill 4 was marked unopened by notAvailable.png, skill 1 was available on battle_screen, skill 8 was available on battle_screen
    assert diff_skill_events[0]["commands"] == [[5, 2], [1, 2], [8, 2]]
    # Skill 5 is on cooldown, so it gets skipped while skills 1 and 8 are tapped with target 2 (640, 440)
    skipped_events = [
        event.data for event in events if event.event_type == "skill_skipped"
    ]
    assert any(item.get("skill_number") == 5 for item in skipped_events)
    assert (786, 590) in device.taps


def test_resolve_free_skill_target_probes_weak_affinity_cards_when_no_buffs_recorded(
    monkeypatch,
) -> None:
    from webapp.automation.battle import _resolve_free_skill_target

    taps: list[tuple[int, int]] = []

    class _DummyContext:
        def emit(self, *_args: Any, **_kwargs: Any) -> None:
            pass

        def sleep(self, _seconds: float) -> None:
            pass

    class _DummyDevice:
        def tap(self, x: int, y: int):
            taps.append((x, y))

            class _Op:
                def to_dict(self) -> dict[str, Any]:
                    return {"type": "tap", "x": x, "y": y}

            return _Op()

    class _DummyCardRecognizer:
        def recognize(self, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
            return {
                "complete": True,
                "recognized_count": 5,
                "cards": [
                    {"slot": 1, "servant": 1, "color": "B", "code": "1B", "affinity_score": 0},
                    {"slot": 2, "servant": 3, "color": "A", "code": "3A", "affinity_score": 1},
                    {"slot": 3, "servant": 2, "color": "Q", "code": "2Q", "affinity_score": 1},
                    {"slot": 4, "servant": 1, "color": "A", "code": "1A", "affinity_score": -1},
                    {"slot": 5, "servant": 2, "color": "B", "code": "2B", "affinity_score": 0},
                ],
            }

    monkeypatch.setattr(
        "webapp.automation.battle._wait_for_command_cards",
        lambda *_args, **_kwargs: b"cards",
    )

    target, probe_taps = _resolve_free_skill_target(
        _DummyContext(),  # type: ignore[arg-type]
        _DummyDevice(),  # type: ignore[arg-type]
        object(),  # type: ignore[arg-type]
        _DummyCardRecognizer(),  # type: ignore[arg-type]
        "CH",
        [
            {"slot": 0, "name": "One", "sn": "101"},
            {"slot": 1, "name": "Two", "sn": "102"},
            {"slot": 2, "name": "Three", "sn": "103"},
            None,
            None,
            None,
        ],
        [0, 1, 2, 3, 4, 5],
        [0, 0, 0, 0, 0, 0],
        set(),
        ["battle/CH/Arts.png", "battle/CH/Buster.png", "battle/CH/Quick.png"],
        "battle/CH/attack.png",
        0.75,
        2.0,
        0.01,
        0.0,
    )
    # Weak cards belong to servants 3 and 2 -> min(weaks) == 2
    assert target == 2
    assert probe_taps == 2
    assert taps == [(1150, 600), (1201, 683)]


