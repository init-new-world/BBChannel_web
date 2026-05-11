from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from webapp.core.errors import AppError, ErrorCode
from webapp.services.resources import ResourceService


def _resource_service(tmp_path: Path) -> ResourceService:
    assets = tmp_path / "assets"
    data = tmp_path / "data"
    assets.mkdir()
    data.mkdir()
    return ResourceService(assets, data)


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
