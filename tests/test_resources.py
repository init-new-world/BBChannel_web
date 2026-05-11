from pathlib import Path

import pytest

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
