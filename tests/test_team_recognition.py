from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from webapp.services.recognition import RecognitionService
from webapp.services.resources import ResourceService
from webapp.services.team import TeamRecognizer


def _pattern(size: tuple[int, int], color: tuple[int, int, int]) -> Image.Image:
    image = Image.new("RGB", size, color)
    draw = ImageDraw.Draw(image)
    draw.rectangle((2, 2, size[0] - 3, size[1] - 3), outline=(245, 215, 65), width=2)
    draw.line((3, size[1] - 4, size[0] - 4, 3), fill=(35, 220, 225), width=3)
    return image


def _png_bytes(image: Image.Image) -> bytes:
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def test_team_recognizer_reports_servant_mismatch_and_matching_master(tmp_path: Path):
    pytest.importorskip("cv2")
    assets = tmp_path / "assets"
    data = tmp_path / "data"
    servant_faces = assets / "servantface"
    master_equips = assets / "masterequip"
    servant_faces.mkdir(parents=True)
    master_equips.mkdir(parents=True)
    data.mkdir()

    first = _pattern((60, 60), (65, 80, 155))
    second = _pattern((60, 60), (145, 65, 90))
    master = _pattern((70, 70), (65, 135, 95))
    first.save(servant_faces / "First_1.png")
    second.save(servant_faces / "Second_1.png")
    master.save(master_equips / "Chaldea_0.png")

    screenshot = Image.new("RGB", (1280, 720), (18, 24, 32))
    screenshot.paste(first, (80, 220))
    screenshot.paste(master, (1010, 560))
    resources = ResourceService(assets, data)
    report = TeamRecognizer(
        resources,
        RecognitionService(resources),
    ).recognize(
        _png_bytes(screenshot),
        {
            "servants": [
                {
                    "slot": 0,
                    "name": "First",
                    "canonical_name": "First",
                    "used": True,
                },
                {
                    "slot": 1,
                    "name": "Second",
                    "canonical_name": "Second",
                    "used": True,
                },
            ],
            "master": {"equip": 7, "name": "Chaldea"},
        },
        threshold=0.99,
    )

    assert report["ok"] is False
    assert report["mismatch_count"] == 1
    assert report["unverified_count"] == 0
    assert report["servants"][0]["status"] == "matched"
    assert report["servants"][0]["template_path"] == "servantface/First_1.png"
    assert report["servants"][1]["status"] == "mismatch"
    assert report["master"]["status"] == "matched"
    assert report["master"]["template_path"] == "masterequip/Chaldea_0.png"


def test_team_recognizer_detects_craft_essence_card_back_in_configured_slots(tmp_path: Path):
    pytest.importorskip("cv2")
    assets = tmp_path / "assets"
    data = tmp_path / "data"
    public_battle = assets / "battle" / "public"
    public_battle.mkdir(parents=True)
    data.mkdir()

    gold_back = _pattern((60, 80), (195, 165, 45))
    gold_back.save(public_battle / "goldBack.png")

    resources = ResourceService(assets, data)
    recognizer = TeamRecognizer(resources, RecognitionService(resources))

    # Card back pasted into slot 1 ROI (x ~ 250..450, y ~ 173..367)
    slot1_flip = Image.new("RGB", (1280, 720), (18, 24, 32))
    slot1_flip.paste(gold_back, (280, 220))

    assert (
        recognizer.has_craft_essence_card_back(
            _png_bytes(slot1_flip),
            {"servants": [{"slot": 0, "used": True}, {"slot": 1, "used": False}]},
            threshold=0.95,
        )
        is False
    )
    assert (
        recognizer.has_craft_essence_card_back(
            _png_bytes(slot1_flip),
            {"servants": [{"slot": 0, "used": True}, {"slot": 1, "used": True}]},
            threshold=0.95,
        )
        is True
    )
