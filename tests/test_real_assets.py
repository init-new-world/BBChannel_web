from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image, ImageChops

from webapp.services.resources import ResourceService


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _png_bytes(image: Image.Image) -> bytes:
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def test_real_lfs_template_indexes_matches_and_renders_debug_overlay():
    pytest.importorskip("cv2")
    from webapp.services.recognition import RecognitionService

    resources = ResourceService(PROJECT_ROOT / "assets", PROJECT_ROOT / "data")
    template_path = "battle/CH/AP.png"

    page = resources.template_index(prefix="battle/CH", query="AP.png", limit=20)
    assert template_path in [entry["path"] for entry in page["entries"]]

    metadata = resources.template_metadata(template_path)
    assert metadata["format"] == "PNG"
    assert metadata["width"] == 44
    assert metadata["height"] == 33

    with Image.open(resources.resolve_template(template_path)) as source:
        template = source.convert("RGB")
    scaled = template.resize((66, 50), Image.Resampling.BILINEAR)
    screenshot = Image.new("RGB", (280, 180), (19, 27, 37))
    screenshot.paste(scaled, (143, 89))
    screenshot_bytes = _png_bytes(screenshot)

    result, overlay_bytes = RecognitionService(resources).match_template_debug(
        screenshot_bytes,
        template_path,
        threshold=0.9,
        roi=[120, 70, 120, 90],
        scales=[1.0, 1.5],
    )

    overlay = Image.open(BytesIO(overlay_bytes)).convert("RGB")
    assert result.matched is True
    assert result.confidence >= 0.99
    assert result.scale == 1.5
    assert result.top_left == [143, 89]
    assert result.center == [176, 114]
    assert result.size == [66, 50]
    assert result.roi == [120, 70, 120, 90]
    assert overlay.size == screenshot.size
    assert ImageChops.difference(screenshot, overlay).getbbox() is not None


def test_real_command_card_template_matches_with_transparency():
    pytest.importorskip("cv2")
    from webapp.services.recognition import RecognitionService

    resources = ResourceService(PROJECT_ROOT / "assets", PROJECT_ROOT / "data")
    template_path = "commands_CH/100100/card_servant_1.png"
    with Image.open(resources.resolve_template(template_path)) as source:
        template = source.convert("RGBA")
    screenshot = Image.new("RGB", (500, 400), (40, 70, 110))
    screenshot.paste(template, (140, 80), template)

    result = RecognitionService(resources).match_template(
        _png_bytes(screenshot),
        template_path,
        threshold=0.95,
    )

    assert result.matched is True
    assert result.confidence >= 0.98
    assert result.top_left == [140, 80]
