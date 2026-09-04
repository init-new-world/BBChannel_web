from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from webapp.core.errors import AppError, ErrorCode
from webapp.services.assist_tags import AssistTagService
from webapp.services.resources import ResourceService


def _png_bytes(image: Image.Image) -> bytes:
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def test_build_assist_tag_crops_image_and_records_anchor_metadata(tmp_path: Path):
    assets = tmp_path / "assets"
    data = tmp_path / "data"
    assets.mkdir()
    data.mkdir()
    service = AssistTagService(ResourceService(assets, data))
    screenshot = Image.new("RGB", (1280, 720), (18, 24, 32))
    ImageDraw.Draw(screenshot).rectangle((250, 120, 289, 149), fill=(220, 70, 135))

    result = service.build(
        label="Guild",
        screenshot=_png_bytes(screenshot),
        anchor=[100, 95],
        bounds=[250, 120, 290, 150],
        threshold=0.85,
    )

    expected_name = "[Guild]W1280H720DXL150DXR190DYT25DYB55CON85.png"
    assert result["name"] == expected_name
    assert result["threshold"] == 0.85
    assert result["source_size"] == [1280, 720]
    assert result["offsets"] == [150, 25, 190, 55]
    assert result["image_size"] == [40, 30]
    assert service.inventory() == [result]
    saved = Image.open(BytesIO(service.read_image(expected_name)))
    assert saved.size == (40, 30)
    assert saved.getpixel((20, 15)) == (220, 70, 135)


def test_import_assist_tag_requires_filename_dimensions_to_match_image(tmp_path: Path):
    assets = tmp_path / "assets"
    data = tmp_path / "data"
    assets.mkdir()
    data.mkdir()
    service = AssistTagService(ResourceService(assets, data))
    filename = "[Guild]W1280H720DXL150DXR190DYT25DYB55CON85.png"

    with pytest.raises(AppError) as exc_info:
        service.import_image(
            filename,
            _png_bytes(Image.new("RGB", (39, 30), "red")),
        )

    assert exc_info.value.code == ErrorCode.DATA_FILE_INVALID
    assert exc_info.value.details["expected_size"] == [40, 30]
    assert exc_info.value.details["actual_size"] == [39, 30]


def test_delete_assist_tag_refreshes_resource_index(tmp_path: Path):
    assets = tmp_path / "assets"
    data = tmp_path / "data"
    assets.mkdir()
    data.mkdir()
    resources = ResourceService(assets, data)
    service = AssistTagService(resources)
    filename = "[Badge]W1280H720DXL10DXR30DYT20DYB40CON8.png"
    service.import_image(filename, _png_bytes(Image.new("RGB", (20, 20), "blue")))
    assert f"assist/assist_tags/{filename}" in resources.list_templates()

    result = service.delete(filename)

    assert result == {"name": filename, "deleted": True}
    assert f"assist/assist_tags/{filename}" not in resources.list_templates()


def test_import_assist_tag_rejects_path_names(tmp_path: Path):
    assets = tmp_path / "assets"
    data = tmp_path / "data"
    assets.mkdir()
    data.mkdir()
    service = AssistTagService(ResourceService(assets, data))

    with pytest.raises(AppError) as exc_info:
        service.import_image(
            "../[Tag]W1280H720DXL0DXR20DYT0DYB20CON8.png",
            _png_bytes(Image.new("RGB", (20, 20), "blue")),
        )

    assert exc_info.value.code == ErrorCode.DATA_FILE_INVALID
