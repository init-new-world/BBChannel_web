from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image, ImageChops, ImageDraw

from webapp.core.errors import AppError, ErrorCode
from webapp.services.resources import ResourceService


def _resource_service(tmp_path: Path) -> ResourceService:
    assets = tmp_path / "assets"
    data = tmp_path / "data"
    assets.mkdir()
    data.mkdir()
    return ResourceService(assets, data)


def _pattern(size: tuple[int, int] = (12, 10)) -> Image.Image:
    image = Image.new("RGB", size, "black")
    draw = ImageDraw.Draw(image)
    draw.rectangle((1, 1, size[0] - 2, size[1] - 2), outline="white", width=1)
    draw.line((1, size[1] - 2, size[0] - 2, 1), fill="red", width=2)
    draw.rectangle((2, 2, 4, 4), fill="green")
    return image


def _png_bytes(image: Image.Image) -> bytes:
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def test_match_template_returns_expected_center(tmp_path: Path):
    pytest.importorskip("cv2")
    from webapp.services.recognition import RecognitionService

    resources = _resource_service(tmp_path)
    template_path = resources.assets_dir / "target.png"

    screenshot = Image.new("RGB", (80, 60), "black")
    draw = ImageDraw.Draw(screenshot)
    draw.rectangle((25, 18, 44, 37), fill="white")
    draw.line((25, 18, 44, 37), fill="red", width=2)

    template = screenshot.crop((25, 18, 45, 38))
    template.save(template_path)

    buffer = BytesIO()
    screenshot.save(buffer, format="PNG")

    result = RecognitionService(resources).match_template(
        buffer.getvalue(),
        "target.png",
        threshold=0.8,
    )

    assert result.matched is True
    assert result.center == [35, 28]
    assert result.top_left == [25, 18]
    assert result.size == [20, 20]


def test_match_template_reports_opencv_unavailable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from webapp.services import recognition

    monkeypatch.setattr(recognition, "cv2", None)
    resources = _resource_service(tmp_path)

    with pytest.raises(AppError) as excinfo:
        recognition.RecognitionService(resources).match_template(b"png", "target.png")

    assert excinfo.value.code == ErrorCode.OPENCV_UNAVAILABLE


def test_match_template_roi_returns_global_coordinates(tmp_path: Path):
    pytest.importorskip("cv2")
    from webapp.services.recognition import RecognitionService

    resources = _resource_service(tmp_path)
    template = _pattern()
    template.save(resources.assets_dir / "target.png")
    screenshot = Image.new("RGB", (100, 60), "black")
    screenshot.paste(template, (63, 24))

    result = RecognitionService(resources).match_template(
        _png_bytes(screenshot),
        "target.png",
        roi=[50, 10, 40, 40],
    )

    assert result.matched is True
    assert result.top_left == [63, 24]
    assert result.center == [69, 29]
    assert result.roi == [50, 10, 40, 40]


def test_match_template_selects_best_scale(tmp_path: Path):
    pytest.importorskip("cv2")
    from webapp.services.recognition import RecognitionService

    resources = _resource_service(tmp_path)
    template = _pattern()
    template.save(resources.assets_dir / "target.png")
    scaled = template.resize((24, 20), Image.Resampling.BILINEAR)
    screenshot = Image.new("RGB", (100, 70), "black")
    screenshot.paste(scaled, (31, 27))

    result = RecognitionService(resources).match_template(
        _png_bytes(screenshot),
        "target.png",
        scales=[1.0, 1.5, 2.0],
    )

    assert result.matched is True
    assert result.scale == 2.0
    assert result.top_left == [31, 27]
    assert result.size == [24, 20]


def test_match_template_supports_explicit_template_size(tmp_path: Path):
    pytest.importorskip("cv2")
    from webapp.services.recognition import RecognitionService

    resources = _resource_service(tmp_path)
    template = _pattern((10, 20))
    template.save(resources.assets_dir / "forced-size.png")
    resized = template.resize((30, 30), Image.Resampling.BILINEAR)
    screenshot = Image.new("RGB", (100, 70), (8, 12, 18))
    screenshot.paste(resized, (41, 23))

    result = RecognitionService(resources).match_template(
        _png_bytes(screenshot),
        "forced-size.png",
        threshold=0.9,
        template_size=(30, 30),
    )

    assert result.matched is True
    assert result.top_left == [41, 23]
    assert result.size == [30, 30]


def test_match_template_uses_alpha_channel_as_mask(tmp_path: Path):
    pytest.importorskip("cv2")
    from webapp.services.recognition import RecognitionService

    resources = _resource_service(tmp_path)
    template = Image.new("RGBA", (30, 30), (0, 0, 0, 0))
    draw = ImageDraw.Draw(template)
    draw.rectangle((10, 10, 19, 19), fill=(255, 20, 20, 255))
    draw.line((10, 10, 19, 19), fill=(20, 255, 20, 255), width=2)
    template.save(resources.assets_dir / "alpha.png")
    screenshot = Image.new("RGB", (100, 70), (40, 90, 140))
    screenshot.paste(template, (45, 22), template)

    result = RecognitionService(resources).match_template(
        _png_bytes(screenshot),
        "alpha.png",
        threshold=0.95,
    )

    assert result.matched is True
    assert result.top_left == [45, 22]


def test_match_template_uses_explicit_mask_path(tmp_path: Path):
    pytest.importorskip("cv2")
    from webapp.services.recognition import RecognitionService

    resources = _resource_service(tmp_path)
    template = Image.new("L", (20, 20), 10)
    draw = ImageDraw.Draw(template)
    draw.rectangle((7, 6, 12, 13), fill=220)
    draw.line((7, 6, 12, 13), fill=90, width=2)
    template.save(resources.assets_dir / "digit.png")
    mask = Image.new("L", template.size, 0)
    ImageDraw.Draw(mask).rectangle((7, 6, 12, 13), fill=255)
    mask.save(resources.assets_dir / "digit-mask.png")

    screenshot = Image.new("RGB", (80, 60), (80, 120, 160))
    visible = template.crop((7, 6, 13, 14)).convert("RGB")
    screenshot.paste(visible, (39, 24))

    result = RecognitionService(resources).match_template(
        _png_bytes(screenshot),
        "digit.png",
        threshold=0.95,
        mask_path="digit-mask.png",
    )

    assert result.matched is True
    assert result.top_left == [32, 18]


def test_match_templates_decodes_screenshot_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    cv = pytest.importorskip("cv2")
    from webapp.services.recognition import RecognitionService

    resources = _resource_service(tmp_path)
    first = _pattern()
    second = _pattern((8, 8))
    first.save(resources.assets_dir / "first.png")
    second.save(resources.assets_dir / "second.png")
    screenshot = Image.new("RGB", (80, 60), "black")
    screenshot.paste(first, (10, 10))
    screenshot.paste(second, (50, 30))
    decode_calls = 0
    original_decode = cv.imdecode

    def count_decode(*args, **kwargs):
        nonlocal decode_calls
        decode_calls += 1
        return original_decode(*args, **kwargs)

    monkeypatch.setattr(cv, "imdecode", count_decode)
    results = RecognitionService(resources).match_templates(
        _png_bytes(screenshot),
        [
            {"template_path": "first.png", "threshold": 0.8},
            {"template_path": "second.png", "threshold": 0.8},
        ],
    )

    assert decode_calls == 1
    assert [result.template_path for result in results] == ["first.png", "second.png"]
    assert all(result.matched for result in results)


def test_match_template_all_returns_distinct_occurrences(tmp_path: Path):
    pytest.importorskip("cv2")
    from webapp.services.recognition import RecognitionService

    resources = _resource_service(tmp_path)
    template = _pattern()
    template.save(resources.assets_dir / "target.png")
    screenshot = Image.new("RGB", (100, 70), "black")
    screenshot.paste(template, (12, 9))
    screenshot.paste(template, (67, 43))

    results = RecognitionService(resources).match_template_all(
        _png_bytes(screenshot),
        "target.png",
        threshold=0.99,
        max_results=5,
    )

    assert [result.top_left for result in results] == [[12, 9], [67, 43]]
    assert all(result.matched for result in results)
    assert all(result.confidence >= 0.99 for result in results)


def test_match_template_rejects_roi_outside_screenshot(tmp_path: Path):
    pytest.importorskip("cv2")
    from webapp.services.recognition import RecognitionService

    resources = _resource_service(tmp_path)
    _pattern().save(resources.assets_dir / "target.png")

    with pytest.raises(AppError) as exc_info:
        RecognitionService(resources).match_template(
            _png_bytes(Image.new("RGB", (40, 30), "black")),
            "target.png",
            roi=[35, 20, 10, 10],
        )

    assert exc_info.value.code == ErrorCode.MATCH_FAILED


def test_match_template_debug_renders_roi_match_box_and_label(tmp_path: Path):
    pytest.importorskip("cv2")
    from webapp.services.recognition import RecognitionService

    resources = _resource_service(tmp_path)
    template = _pattern()
    template.save(resources.assets_dir / "target.png")
    screenshot = Image.new("RGB", (100, 60), "black")
    screenshot.paste(template, (63, 24))
    screenshot_bytes = _png_bytes(screenshot)

    result, overlay_bytes = RecognitionService(resources).match_template_debug(
        screenshot_bytes,
        "target.png",
        threshold=0.8,
        roi=[50, 10, 40, 40],
        scales=[1.0],
    )

    overlay = Image.open(BytesIO(overlay_bytes)).convert("RGB")
    difference = ImageChops.difference(screenshot, overlay)
    assert result.top_left == [63, 24]
    assert overlay.size == screenshot.size
    assert difference.getbbox() is not None
