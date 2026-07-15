from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from webapp.services.cards import CommandCardRecognizer
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


def test_command_card_recognizer_classifies_five_slots(tmp_path: Path):
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

    screenshot = Image.new("RGB", (1280, 720), (18, 24, 32))
    expected = [(1, "B"), (2, "A"), (3, "Q"), (1, "A"), (2, "B")]
    expected_stars = [5, 0, 10, 2, 9]
    color_names = {"B": "Buster", "A": "Arts", "Q": "Quick"}
    star_rois = ((73, 353), (329, 353), (584, 353), (841, 353), (1101, 353))
    for slot, ((position, color), stars) in enumerate(zip(expected, expected_stars, strict=True)):
        x = slot * 256
        screenshot.paste(colors[color_names[color]], (x + 20, 420), colors[color_names[color]])
        portrait = servant_templates[position]
        screenshot.paste(portrait, (x + 100, 500), portrait)
        if stars:
            template_number = 0 if stars == 10 else stars
            screenshot.paste(star_templates[template_number].convert("RGB"), star_rois[slot])

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
    )

    assert result["complete"] is True
    assert result["recognized_count"] == 5
    assert [card["code"] for card in result["cards"]] == ["1B", "2A", "3Q", "1A", "2B"]
    assert [card["slot"] for card in result["cards"]] == [1, 2, 3, 4, 5]
    assert [card["stars"] for card in result["cards"]] == expected_stars
    assert result["cards"][1]["star_confidence"] is None
    assert all(
        card["star_confidence"] >= 0.99
        for card in result["cards"]
        if card["stars"]
    )
    assert all(card["color_confidence"] >= 0.99 for card in result["cards"])
    assert all(card["servant_confidence"] >= 0.99 for card in result["cards"])
