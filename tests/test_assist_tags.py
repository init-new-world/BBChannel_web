from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from webapp.core.errors import AppError, ErrorCode
from webapp.services.assist_tags import AssistTagService, parse_assist_tag_filename
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


@pytest.mark.parametrize("threshold,code", [
    (0.01, "01"), (0.05, "05"), (0.8, "8"), (0.805, "805"),
    (0.999, "999"), (0.001, "001"), (1e-8, "00000001"),
])
def test_assist_tag_threshold_round_trips_without_rounding(tmp_path: Path, threshold, code):
    service = AssistTagService(ResourceService(tmp_path / "assets", tmp_path / "data"))

    result = service.build(
        label="Precise", screenshot=_png_bytes(Image.new("RGB", (20, 20), "red")),
        anchor=[0, 0], bounds=[0, 0, 10, 10], threshold=threshold,
    )

    assert result["name"].endswith(f"CON{code}.png")
    assert result["threshold"] == threshold
    assert parse_assist_tag_filename(result["name"]).threshold == threshold


def test_assist_tag_rejects_unrepresentable_threshold_before_writing(tmp_path: Path):
    service = AssistTagService(ResourceService(tmp_path / "assets", tmp_path / "data"))
    with pytest.raises(AppError) as exc_info:
        service.build(
            label="Tiny", screenshot=_png_bytes(Image.new("RGB", (20, 20), "red")),
            anchor=[0, 0], bounds=[0, 0, 10, 10], threshold=1e-100,
        )
    assert exc_info.value.code == ErrorCode.DATA_FILE_INVALID
    assert "precision" in exc_info.value.message.lower()
    assert service.inventory() == []


@pytest.mark.parametrize("link_directory", [False, True])
def test_assist_tags_reject_symlinks_without_touching_the_target(tmp_path: Path, link_directory):
    assets = tmp_path / "assets"
    directory = assets / "assist" / "assist_tags"
    outside = tmp_path / "outside"
    outside.mkdir()
    filename = "[Outside]W1280H720DXL0DXR20DYT0DYB20CON8.png"
    original = _png_bytes(Image.new("RGB", (20, 20), "blue"))
    target = outside / filename
    target.write_bytes(original)
    if link_directory:
        directory.parent.mkdir(parents=True)
        directory.symlink_to(outside, target_is_directory=True)
    else:
        directory.mkdir(parents=True)
        (directory / filename).symlink_to(target)
    service = AssistTagService(ResourceService(assets, tmp_path / "data"))

    assert service.inventory() == []
    for operation in (
        lambda: service.read_image(filename),
        lambda: service.delete(filename),
        lambda: service.import_image(filename, original, overwrite=True),
    ):
        with pytest.raises(AppError) as exc_info:
            operation()
        assert exc_info.value.code == ErrorCode.DATA_FILE_INVALID
        assert target.read_bytes() == original
