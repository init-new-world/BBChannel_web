from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from webapp.automation.battle import (
    _apply_servant_exchange,
    _apply_servant_replacements,
    _frontline_servants,
    _servant_positions,
)
from webapp.services.cards import CARD_ASSIST_ROIS, WEAK_RESIST_ROIS, CommandCardRecognizer
from webapp.services.recognition import RecognitionService
from webapp.services.resources import ResourceService


def _pattern(size: tuple[int, int], color: tuple[int, int, int], marker: int) -> Image.Image:
    image = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rectangle((2, 2, size[0] - 3, size[1] - 3), fill=(*color, 255))
    draw.line((marker, 3, size[0] - 4, size[1] - marker), fill=(255, 255, 255, 255), width=2)
    return image


def _png_bytes(image: Image.Image) -> bytes:
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.mark.parametrize("blocked,obscured", [(None, False), ("freeze", False), ("bjfy", False), ("freeze", True)])
def test_command_card_recognizer_classifies_five_slots(tmp_path: Path, blocked, obscured):
    pytest.importorskip("cv2")
    assets = tmp_path / "assets"
    data = tmp_path / "data"
    (assets / "battle" / "CH").mkdir(parents=True)
    data.mkdir()

    colors = {
        "Buster": _pattern((34, 20), (210, 40, 40), 4),
        "Arts": _pattern((34, 20), (40, 80, 220), 8),
        "Quick": _pattern((34, 20), (40, 190, 80), 12),
    }
    for name, template in colors.items():
        template.save(assets / "battle" / "CH" / f"{name}.png")
    blockers = {
        "freeze": _pattern((20, 30), (220, 200, 30), 4),
        "bjfy": _pattern((22, 28), (150, 40, 210), 11),
    }
    for name, template in blockers.items():
        template.save(assets / "battle" / "CH" / f"{name}.png")

    star_directory = assets / "battle" / "public" / "starNum"
    star_directory.mkdir(parents=True)
    star_templates = {}
    for number in range(10):
        template = Image.new("L", (40, 39), 0)
        draw = ImageDraw.Draw(template)
        draw.rectangle((5, 5, 34, 33), fill=20 + number * 15)
        draw.line((6 + number * 2, 6, 8 + number * 2, 32), fill=240, width=2)
        template.save(star_directory / f"n{number}.png")
        mask = Image.new("L", template.size, 0)
        ImageDraw.Draw(mask).rectangle((5, 5, 34, 33), fill=255)
        mask.save(star_directory / f"n{number}mask.png")
        star_templates[number] = template

    servant_templates = {}
    for position, sn in enumerate(("100", "101", "102"), start=1):
        directory = assets / "commands_CH" / sn
        directory.mkdir(parents=True)
        template = _pattern((48, 48), (50 * position, 40, 180 - 30 * position), 5 * position)
        template.save(directory / "card_servant_1.png")
        servant_templates[position] = template

    special_directory = assets / "special_keys"
    special_directory.mkdir()
    special_template = _pattern((24, 24), (220, 170, 30), 7)
    special_template.save(special_directory / "special.png")

    screenshot = Image.new("RGB", (1280, 720), (18, 24, 32))
    expected = [(1, "B"), (2, "A"), (3, "Q"), (1, "A"), (2, "B")]
    expected_stars = [5, 0, 10, 2, 9]
    color_names = {"B": "Buster", "A": "Arts", "Q": "Quick"}
    star_rois = ((73, 353), (329, 353), (584, 353), (841, 353), (1101, 353))
    for slot, ((position, color), stars) in enumerate(zip(expected, expected_stars, strict=True)):
        x = slot * 256
        if not (obscured and slot == 1):
            screenshot.paste(colors[color_names[color]], (x + 20, 420), colors[color_names[color]])
            portrait = servant_templates[position]
            screenshot.paste(portrait, (x + 100, 500), portrait)
        if stars:
            template_number = 0 if stars == 10 else stars
            screenshot.paste(star_templates[template_number].convert("RGB"), star_rois[slot])
        if slot == 1:
            screenshot.paste(special_template, (x + 180, 620), special_template)
            if blocked:
                screenshot.paste(blockers[blocked], (441, 479), blockers[blocked])

    resources = ResourceService(assets, data)
    result = CommandCardRecognizer(
        resources,
        RecognitionService(resources),
    ).recognize(
        _png_bytes(screenshot),
        "CH",
        [
            {"slot": 0, "name": "One", "active": True, "sn": "100"},
            {"slot": 1, "name": "Two", "active": True, "sn": "101"},
            {"slot": 2, "name": "Three", "active": True, "sn": "102"},
        ],
        threshold=0.85,
        special_keys=[
            {
                "code": "S0",
                "template_path": "special_keys/special.png",
                "threshold": 0.99,
            }
        ],
    )

    assert result["complete"] is True
    assert result["recognized_count"] == (4 if blocked else 5)
    assert [card["code"] for card in result["cards"]] == ["1B", None if blocked else "2A", "3Q", "1A", "2B"]
    assert [card["available"] for card in result["cards"]] == [True, not bool(blocked), True, True, True]
    assert result["available_count"] == (4 if blocked else 5)
    assert result["cards"][1]["blocked_reason"] == ({"freeze": "immobilized", "bjfy": "sealed"}.get(blocked))
    assert [card["slot"] for card in result["cards"]] == [1, 2, 3, 4, 5]
    assert [card["stars"] for card in result["cards"]] == expected_stars
    assert [card["special_keys"] for card in result["cards"]] == [
        [],
        ["S0"],
        [],
        [],
        [],
    ]
    assert result["cards"][1]["star_confidence"] is None
    assert all(
        card["star_confidence"] >= 0.99
        for card in result["cards"]
        if card["stars"]
    )
    assert all(card["color_confidence"] >= 0.99 for card in result["cards"] if card["code"])
    assert all(card["servant_confidence"] >= 0.99 for card in result["cards"] if card["code"])


def test_command_card_recognizer_disambiguates_duplicate_frontline_support_and_unnamed_assist(
    tmp_path: Path,
):
    pytest.importorskip("cv2")
    assets = tmp_path / "assets"
    data = tmp_path / "data"
    (assets / "battle" / "CH").mkdir(parents=True)
    data.mkdir()

    colors = {
        "Buster": _pattern((34, 20), (210, 40, 40), 4),
        "Arts": _pattern((34, 20), (40, 80, 220), 8),
        "Quick": _pattern((34, 20), (40, 190, 80), 12),
    }
    for name, template in colors.items():
        template.save(assets / "battle" / "CH" / f"{name}.png")
    for name, color, marker in (("freeze", (220, 200, 30), 4), ("bjfy", (150, 40, 210), 11)):
        _pattern((20, 30), color, marker).save(assets / "battle" / "CH" / f"{name}.png")
    assist_badge = _pattern((33, 25), (245, 190, 45), 6)
    assist_badge.save(assets / "battle" / "CH" / "assist.png")

    star_directory = assets / "battle" / "public" / "starNum"
    star_directory.mkdir(parents=True)
    for number in range(10):
        template = Image.new("L", (40, 39), 0)
        draw = ImageDraw.Draw(template)
        draw.rectangle((5, 5, 34, 33), fill=20 + number * 15)
        draw.line((6 + number * 2, 6, 8 + number * 2, 32), fill=240, width=2)
        template.save(star_directory / f"n{number}.png")
        mask = Image.new("L", template.size, 0)
        ImageDraw.Draw(mask).rectangle((5, 5, 34, 33), fill=255)
        mask.save(star_directory / f"n{number}mask.png")

    servant_templates = {}
    for sn, color, marker in (("100", (60, 40, 160), 5), ("101", (140, 50, 120), 10)):
        directory = assets / "commands_CH" / sn
        directory.mkdir(parents=True)
        template = _pattern((48, 48), color, marker)
        template.save(directory / "card_servant_1.png")
        servant_templates[sn] = template

    screenshot = Image.new("RGB", (1280, 720), (18, 24, 32))
    # Slots 1 and 4 are own servant "100" (position 1); slots 3 and 5 are support copy of "100" (position 3).
    slots = [
        ("100", "Buster", False),
        ("101", "Arts", False),
        ("100", "Quick", True),
        ("100", "Arts", False),
        ("100", "Buster", True),
    ]
    for slot_index, (sn, color_name, is_support) in enumerate(slots):
        x = slot_index * 256
        screenshot.paste(colors[color_name], (x + 20, 420), colors[color_name])
        portrait = servant_templates[sn]
        screenshot.paste(portrait, (x + 100, 500), portrait)
        if is_support:
            assist_x, assist_y, _, _ = CARD_ASSIST_ROIS[slot_index]
            screenshot.paste(assist_badge, (assist_x + 10, assist_y + 8), assist_badge)

    resources = ResourceService(assets, data)
    recognizer = CommandCardRecognizer(resources, RecognitionService(resources))

    positions = _servant_positions(
        [
            {"slot": 0, "name": "Castoria", "active": True, "sn": "100"},
            {"slot": 1, "name": "Attacker", "active": True, "sn": "101"},
            {"slot": 2, "name": "Castoria", "active": True, "sn": "100"},
            {"slot": 3, "name": "Backline", "active": False, "sn": "101"},
        ],
        assist_slot=2,
    )
    result = recognizer.recognize(
        _png_bytes(screenshot),
        "CH",
        _frontline_servants(positions),
        threshold=0.85,
    )

    assert result["complete"] is True
    assert [card["code"] for card in result["cards"]] == ["1B", "2A", "3Q", "1A", "3B"]
    assert [card["is_assist"] for card in result["cards"]] == [False, False, True, False, True]

    # Swap support servant from position 3 to backline position 4, then bring it to position 2 via replacement.
    _apply_servant_exchange(positions, [3, 4])
    assert [servant.get("is_assist", False) for servant in _frontline_servants(positions)] == [
        False,
        False,
        False,
    ]
    _apply_servant_replacements(positions, {"2": 4, "4": None})
    assert [servant.get("is_assist", False) for servant in _frontline_servants(positions)] == [
        False,
        True,
        False,
    ]

    # Even if the support slot has no configured servant name/SN (e.g. CE-only or any-support mode),
    # cards bearing the assist badge still resolve to the support slot's frontline position.
    unnamed_support_positions = _servant_positions(
        [
            {"slot": 0, "name": "Castoria", "active": True, "sn": "100"},
            {"slot": 1, "name": "Attacker", "active": True, "sn": "101"},
            {"slot": 2, "name": None, "active": False, "sn": None},
        ],
        assist_slot=2,
    )
    unnamed_result = recognizer.recognize(
        _png_bytes(screenshot),
        "CH",
        _frontline_servants(unnamed_support_positions),
        threshold=0.85,
    )
    assert unnamed_result["complete"] is True
    assert [card["code"] for card in unnamed_result["cards"]] == ["1B", "2A", "3Q", "1A", "3B"]
    assert [card["is_assist"] for card in unnamed_result["cards"]] == [False, False, True, False, True]


def test_command_card_recognizer_classifies_weak_and_resist_affinities(tmp_path: Path):
    pytest.importorskip("cv2")
    assets = tmp_path / "assets"
    data = tmp_path / "data"
    (assets / "battle" / "CH").mkdir(parents=True)
    data.mkdir()

    colors = {
        "Buster": _pattern((34, 20), (210, 40, 40), 4),
        "Arts": _pattern((34, 20), (40, 80, 220), 8),
        "Quick": _pattern((34, 20), (40, 190, 80), 12),
    }
    for name, template in colors.items():
        template.save(assets / "battle" / "CH" / f"{name}.png")
    for name, color, marker in (("freeze", (220, 200, 30), 4), ("bjfy", (150, 40, 210), 11)):
        _pattern((20, 30), color, marker).save(assets / "battle" / "CH" / f"{name}.png")
    weak_badge = _pattern((36, 22), (250, 75, 55), 5)
    resist_badge = _pattern((36, 22), (70, 145, 245), 11)
    weak_badge.save(assets / "battle" / "CH" / "weak.png")
    resist_badge.save(assets / "battle" / "CH" / "resist.png")

    star_directory = assets / "battle" / "public" / "starNum"
    star_directory.mkdir(parents=True)
    for number in range(10):
        template = Image.new("L", (40, 39), 0)
        ImageDraw.Draw(template).rectangle((5, 5, 34, 33), fill=20 + number * 15)
        template.save(star_directory / f"n{number}.png")
        mask = Image.new("L", template.size, 0)
        ImageDraw.Draw(mask).rectangle((5, 5, 34, 33), fill=255)
        mask.save(star_directory / f"n{number}mask.png")

    servant_templates = {}
    for sn, color, marker in (
        ("100", (60, 40, 160), 5),
        ("101", (140, 50, 120), 10),
        ("102", (50, 160, 110), 14),
    ):
        directory = assets / "commands_CH" / sn
        directory.mkdir(parents=True)
        template = _pattern((48, 48), color, marker)
        template.save(directory / "card_servant_1.png")
        servant_templates[sn] = template

    screenshot = Image.new("RGB", (1280, 720), (18, 24, 32))
    slots = [
        ("100", "Buster", "weak"),
        ("101", "Arts", "neutral"),
        ("102", "Quick", "resist"),
        ("100", "Arts", "weak"),
        ("102", "Buster", "resist"),
    ]
    for slot_index, (sn, color_name, affinity) in enumerate(slots):
        x = slot_index * 256
        screenshot.paste(colors[color_name], (x + 20, 420), colors[color_name])
        portrait = servant_templates[sn]
        screenshot.paste(portrait, (x + 100, 500), portrait)
        roi_x, roi_y, _, _ = WEAK_RESIST_ROIS[slot_index]
        if affinity == "weak":
            screenshot.paste(weak_badge, (roi_x + 12, roi_y + 20), weak_badge)
        elif affinity == "resist":
            screenshot.paste(resist_badge, (roi_x + 12, roi_y + 20), resist_badge)

    resources = ResourceService(assets, data)
    recognizer = CommandCardRecognizer(resources, RecognitionService(resources))
    result = recognizer.recognize(
        _png_bytes(screenshot),
        "CH",
        [
            {"slot": 0, "name": "One", "active": True, "sn": "100"},
            {"slot": 1, "name": "Two", "active": True, "sn": "101"},
            {"slot": 2, "name": "Three", "active": True, "sn": "102"},
        ],
        threshold=0.85,
    )

    assert result["complete"] is True
    assert [card["affinity"] for card in result["cards"]] == [
        "weak",
        "neutral",
        "resist",
        "weak",
        "resist",
    ]
    assert [card["affinity_score"] for card in result["cards"]] == [1, 0, -1, 1, -1]
    assert result["cards"][0]["affinity_confidence"] >= 0.99
    assert result["cards"][1]["affinity_confidence"] is None
    assert result["cards"][2]["affinity_confidence"] >= 0.99


