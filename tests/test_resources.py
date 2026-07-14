from pathlib import Path

import pytest
from PIL import Image

from webapp.core.errors import AppError, ErrorCode
from webapp.services.resources import ResourceService


def test_resolve_template_accepts_existing_relative_image(tmp_path: Path):
    assets = tmp_path / "assets"
    data = tmp_path / "data"
    template = assets / "battle" / "CH" / "start_battle.png"
    template.parent.mkdir(parents=True)
    template.write_bytes(b"png")
    data.mkdir()

    service = ResourceService(assets, data)

    assert service.resolve_template("battle/CH/start_battle.png") == template


def test_resolve_template_rejects_path_traversal(tmp_path: Path):
    assets = tmp_path / "assets"
    data = tmp_path / "data"
    assets.mkdir()
    data.mkdir()
    service = ResourceService(assets, data)

    with pytest.raises(AppError) as excinfo:
        service.resolve_template("../secret.png")

    assert excinfo.value.code == ErrorCode.TEMPLATE_NOT_FOUND


def test_resolve_template_rejects_missing_template(tmp_path: Path):
    assets = tmp_path / "assets"
    data = tmp_path / "data"
    assets.mkdir()
    data.mkdir()
    service = ResourceService(assets, data)

    with pytest.raises(AppError) as excinfo:
        service.resolve_template("missing.png")

    assert excinfo.value.code == ErrorCode.TEMPLATE_NOT_FOUND


def test_list_templates_returns_supported_images(tmp_path: Path):
    assets = tmp_path / "assets"
    data = tmp_path / "data"
    (assets / "battle" / "CH").mkdir(parents=True)
    (assets / "battle" / "CH" / "start_battle.png").write_bytes(b"png")
    (assets / "battle" / "CH" / "notes.txt").write_text("ignore", encoding="utf-8")
    (assets / "assist").mkdir()
    (assets / "assist" / "icon.jpg").write_bytes(b"jpg")
    data.mkdir()

    service = ResourceService(assets, data)

    assert service.list_templates() == [
        "assist/icon.jpg",
        "battle/CH/start_battle.png",
    ]


def test_template_index_filters_searches_and_paginates(tmp_path: Path):
    assets = tmp_path / "assets"
    data = tmp_path / "data"
    (assets / "battle" / "CH").mkdir(parents=True)
    (assets / "battle" / "JP").mkdir(parents=True)
    (assets / "assist").mkdir()
    (assets / "battle" / "CH" / "Start_Battle.png").write_bytes(b"first")
    (assets / "battle" / "CH" / "battle_end.png").write_bytes(b"second")
    (assets / "battle" / "JP" / "start_battle.png").write_bytes(b"third")
    (assets / "assist" / "start.png").write_bytes(b"fourth")
    data.mkdir()
    service = ResourceService(assets, data)

    page = service.template_index(
        prefix="battle/CH",
        query="BATTLE",
        offset=1,
        limit=1,
    )

    assert page["total"] == 2
    assert page["offset"] == 1
    assert page["limit"] == 1
    assert page["entries"] == [
        {
            "path": "battle/CH/battle_end.png",
            "category": "battle",
            "extension": ".png",
            "size_bytes": 6,
        }
    ]


def test_template_metadata_reads_dimensions_and_color_mode(tmp_path: Path):
    assets = tmp_path / "assets"
    data = tmp_path / "data"
    template = assets / "battle" / "target.png"
    template.parent.mkdir(parents=True)
    Image.new("RGBA", (23, 17), (10, 20, 30, 40)).save(template)
    data.mkdir()
    service = ResourceService(assets, data)

    metadata = service.template_metadata("battle/target.png")

    assert metadata["path"] == "battle/target.png"
    assert metadata["width"] == 23
    assert metadata["height"] == 17
    assert metadata["mode"] == "RGBA"
    assert metadata["format"] == "PNG"


def test_template_index_only_changes_after_explicit_refresh(tmp_path: Path):
    assets = tmp_path / "assets"
    data = tmp_path / "data"
    assets.mkdir()
    data.mkdir()
    service = ResourceService(assets, data)
    assert service.template_index()["total"] == 0
    (assets / "new.png").write_bytes(b"png")

    assert service.template_index()["total"] == 0
    assert service.refresh_template_index() == 1
    assert service.template_index()["total"] == 1
