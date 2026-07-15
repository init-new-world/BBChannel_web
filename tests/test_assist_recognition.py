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


def test_assist_recognizer_filters_candidates_by_friend_marker(tmp_path: Path):
    pytest.importorskip("cv2")
    assets = tmp_path / "assets"
    data = tmp_path / "data"
    servant_faces = assets / "servantface"
    battle_assets = assets / "battle" / "CH"
    servant_faces.mkdir(parents=True)
    battle_assets.mkdir(parents=True)
    data.mkdir()

    portrait = Image.new("RGB", (60, 60), (35, 65, 95))
    portrait_draw = ImageDraw.Draw(portrait)
    portrait_draw.rectangle((8, 8, 51, 51), fill=(210, 100, 170))
    portrait_draw.line((5, 54, 54, 5), fill=(45, 225, 195), width=4)
    portrait.save(servant_faces / "Support_1.png")
    friend = Image.new("RGB", (60, 30), (30, 100, 150))
    friend_draw = ImageDraw.Draw(friend)
    friend_draw.rectangle((3, 3, 56, 26), outline=(245, 225, 75), width=2)
    friend_draw.ellipse((20, 6, 39, 25), fill=(230, 80, 130))
    friend.save(battle_assets / "is_friend.png")

    screenshot = Image.new("RGB", (1280, 380), (18, 24, 32))
    screenshot.paste(portrait, (70, 65))
    screenshot.paste(portrait, (70, 225))
    screenshot.paste(friend, (1100, 280))
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
            "friend_only": True,
        },
        threshold=0.99,
    )

    assert result["candidate_count"] == 1
    assert result["candidates"][0]["anchor"] == [100, 255]
    assert result["candidates"][0]["checks"]["friend"] is True
    assert result["candidates"][0]["checks"]["friend_template"] == (
        "battle/CH/is_friend.png"
    )


def test_assist_recognizer_filters_candidates_by_np_level(tmp_path: Path):
    pytest.importorskip("cv2")
    assets = tmp_path / "assets"
    data = tmp_path / "data"
    servant_faces = assets / "servantface"
    np_assets = assets / "assist" / "np_level_CH"
    servant_faces.mkdir(parents=True)
    np_assets.mkdir(parents=True)
    data.mkdir()

    portrait = Image.new("RGB", (60, 60), (35, 65, 95))
    portrait_draw = ImageDraw.Draw(portrait)
    portrait_draw.rectangle((7, 7, 52, 52), fill=(190, 80, 210))
    portrait_draw.line((6, 53, 53, 6), fill=(60, 230, 170), width=4)
    portrait.save(servant_faces / "Support_1.png")
    level1 = Image.new("RGB", (30, 20), (80, 35, 120))
    level1_draw = ImageDraw.Draw(level1)
    level1_draw.rectangle((3, 3, 26, 16), outline=(240, 210, 70), width=2)
    level1_draw.line((6, 15, 12, 4), fill=(45, 190, 245), width=2)
    level1.save(np_assets / "level1.png")
    level3 = Image.new("RGB", (30, 20), (35, 100, 125))
    level3_draw = ImageDraw.Draw(level3)
    level3_draw.ellipse((4, 3, 25, 17), outline=(245, 120, 70), width=2)
    level3_draw.line((7, 4, 23, 15), fill=(220, 230, 55), width=2)
    level3.save(np_assets / "level3.png")

    screenshot = Image.new("RGB", (800, 380), (18, 24, 32))
    screenshot.paste(portrait, (70, 65))
    screenshot.paste(portrait, (70, 225))
    screenshot.paste(level1, (400, 125))
    screenshot.paste(level3, (400, 285))
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
            "np_level": 2,
        },
        threshold=0.99,
    )

    assert result["candidate_count"] == 1
    assert result["candidates"][0]["anchor"] == [100, 255]
    assert result["candidates"][0]["checks"]["np_level"] == 3
    assert result["candidates"][0]["checks"]["np_level_template"] == (
        "assist/np_level_CH/level3.png"
    )


def test_assist_recognizer_requires_all_requested_level_ten_skills(tmp_path: Path):
    pytest.importorskip("cv2")
    assets = tmp_path / "assets"
    data = tmp_path / "data"
    servant_faces = assets / "servantface"
    skill_assets = assets / "assist" / "full_skill"
    servant_faces.mkdir(parents=True)
    skill_assets.mkdir(parents=True)
    data.mkdir()

    portrait = Image.new("RGB", (60, 60), (45, 70, 105))
    portrait_draw = ImageDraw.Draw(portrait)
    portrait_draw.ellipse((7, 7, 52, 52), fill=(200, 85, 180))
    portrait_draw.line((5, 52, 54, 7), fill=(50, 230, 185), width=4)
    portrait.save(servant_faces / "Support_1.png")
    level_ten = Image.new("RGB", (30, 20), (75, 35, 115))
    level_ten_draw = ImageDraw.Draw(level_ten)
    level_ten_draw.rectangle((2, 2, 27, 17), outline=(245, 210, 65), width=2)
    level_ten_draw.line((5, 15, 24, 4), fill=(40, 195, 245), width=2)
    level_ten.save(skill_assets / "10.png")

    screenshot = Image.new("RGB", (700, 400), (18, 24, 32))
    screenshot.paste(portrait, (70, 65))
    screenshot.paste(portrait, (70, 235))
    for x in (250, 310):
        screenshot.paste(level_ten, (x, 125))
    for x in (250, 310, 370):
        screenshot.paste(level_ten, (x, 295))
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
            "skill_levels": [10, 10, 10],
        },
        threshold=0.99,
    )

    assert result["candidate_count"] == 1
    assert result["candidates"][0]["anchor"] == [100, 265]
    assert result["candidates"][0]["checks"]["skill_levels"] == [10, 10, 10]
    assert len(result["candidates"][0]["checks"]["skill_templates"]) == 3
