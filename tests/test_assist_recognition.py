from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from webapp.services.assist import AssistRecognizer
from webapp.services.recognition import RecognitionService
from webapp.services.resources import ResourceService


def _png_bytes(image: Image.Image) -> bytes:
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def test_assist_recognizer_finds_all_matching_servant_faces(tmp_path: Path):
    pytest.importorskip("cv2")
    assets = tmp_path / "assets"
    data = tmp_path / "data"
    servant_faces = assets / "servantface"
    servant_faces.mkdir(parents=True)
    data.mkdir()

    portrait = Image.new("RGBA", (60, 60), (0, 0, 0, 0))
    draw = ImageDraw.Draw(portrait)
    draw.rectangle((4, 4, 55, 55), fill=(40, 120, 210, 255))
    draw.ellipse((15, 12, 44, 41), fill=(240, 220, 180, 255))
    draw.line((8, 52, 52, 8), fill=(230, 40, 80, 255), width=4)
    portrait.save(servant_faces / "Support_1.png")

    screenshot = Image.new("RGB", (420, 300), (18, 24, 32))
    screenshot.paste(portrait, (70, 65), portrait)
    screenshot.paste(portrait, (70, 185), portrait)
    resources = ResourceService(assets, data)

    result = AssistRecognizer(
        resources,
        RecognitionService(resources),
    ).recognize(
        _png_bytes(screenshot),
        {
            "servant_name": "Support Alias",
            "servant_canonical_name": "Support",
            "servant_sn": "314",
        },
        threshold=0.99,
    )

    assert result["servant_name"] == "Support Alias"
    assert result["servant_canonical_name"] == "Support"
    assert result["servant_sn"] == "314"
    assert result["templates"] == ["servantface/Support_1.png"]
    assert result["candidate_count"] == 2
    assert [candidate["bounds"] for candidate in result["candidates"]] == [
        [70, 65, 60, 60],
        [70, 185, 60, 60],
    ]
    assert [candidate["anchor"] for candidate in result["candidates"]] == [
        [100, 95],
        [100, 215],
    ]
    assert all(candidate["confidence"] >= 0.99 for candidate in result["candidates"])


def test_assist_recognizer_filters_candidates_by_equip_name(tmp_path: Path):
    pytest.importorskip("cv2")
    assets = tmp_path / "assets"
    data = tmp_path / "data"
    servant_faces = assets / "servantface"
    assist_equips = assets / "assist" / "assist_equip"
    servant_faces.mkdir(parents=True)
    assist_equips.mkdir(parents=True)
    data.mkdir()

    portrait = Image.new("RGB", (60, 60), (30, 50, 80))
    portrait_draw = ImageDraw.Draw(portrait)
    portrait_draw.ellipse((8, 5, 51, 48), fill=(220, 180, 90))
    portrait_draw.line((4, 55, 55, 4), fill=(20, 220, 170), width=4)
    portrait.save(servant_faces / "Support_1.png")
    equip = Image.new("RGB", (50, 20), (110, 30, 70))
    equip_draw = ImageDraw.Draw(equip)
    equip_draw.rectangle((3, 3, 46, 16), outline=(245, 220, 80), width=2)
    equip_draw.line((5, 15, 44, 4), fill=(40, 210, 250), width=2)
    equip.save(assist_equips / "Event CE.png")

    screenshot = Image.new("RGB", (420, 380), (18, 24, 32))
    screenshot.paste(portrait, (70, 65))
    screenshot.paste(portrait, (70, 225))
    screenshot.paste(equip, (90, 290))
    resources = ResourceService(assets, data)

    result = AssistRecognizer(
        resources,
        RecognitionService(resources),
    ).recognize(
        _png_bytes(screenshot),
        {
            "servant_name": "Support",
            "servant_canonical_name": "Support",
            "servant_sn": "314",
            "equip_names": ["Event CE"],
        },
        threshold=0.99,
    )

    assert result["candidate_count"] == 1
    assert result["candidates"][0]["anchor"] == [100, 255]
    assert result["candidates"][0]["checks"]["equip_name"] == "Event CE"
    assert result["candidates"][0]["checks"]["equip_template"] == (
        "assist/assist_equip/Event CE.png"
    )


def test_assist_recognizer_filters_candidates_by_limit_break_marker(tmp_path: Path):
    pytest.importorskip("cv2")
    assets = tmp_path / "assets"
    data = tmp_path / "data"
    servant_faces = assets / "servantface"
    assist_assets = assets / "assist"
    servant_faces.mkdir(parents=True)
    assist_assets.mkdir(parents=True)
    data.mkdir()

    portrait = Image.new("RGB", (60, 60), (45, 70, 100))
    portrait_draw = ImageDraw.Draw(portrait)
    portrait_draw.polygon([(8, 50), (30, 5), (52, 50)], fill=(220, 80, 150))
    portrait_draw.line((5, 12, 54, 48), fill=(50, 230, 190), width=3)
    portrait.save(servant_faces / "Support_1.png")
    marker = Image.new("RGB", (15, 15), (100, 30, 130))
    marker_draw = ImageDraw.Draw(marker)
    marker_draw.ellipse((1, 1, 13, 13), fill=(250, 215, 50))
    marker_draw.line((2, 12, 12, 2), fill=(40, 80, 230), width=2)
    marker.save(assist_assets / "满破标记.png")

    screenshot = Image.new("RGB", (420, 380), (18, 24, 32))
    screenshot.paste(portrait, (70, 65))
    screenshot.paste(portrait, (70, 225))
    screenshot.paste(marker, (155, 320))
    resources = ResourceService(assets, data)

    result = AssistRecognizer(
        resources,
        RecognitionService(resources),
    ).recognize(
        _png_bytes(screenshot),
        {
            "servant_name": "Support",
            "servant_canonical_name": "Support",
            "servant_sn": "314",
            "full_limit_break": True,
        },
        threshold=0.99,
    )

    assert result["candidate_count"] == 1
    assert result["candidates"][0]["anchor"] == [100, 255]
    assert result["candidates"][0]["checks"]["full_limit_break"] is True
    assert result["candidates"][0]["checks"]["limit_break_template"] == (
        "assist/满破标记.png"
    )
