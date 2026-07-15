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

