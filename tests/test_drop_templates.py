from io import BytesIO

import pytest
from PIL import Image

from tests.test_api import _client
from webapp.automation.completion import _resolve_drop_template
from webapp.services.resources import ResourceService


def _image(assets, name, color="red"):
    path = assets / name
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (32, 40), color).save(path)
    return path


@pytest.mark.parametrize("configured", [
    "drop/b/item.png", "assets/drop/b/item.png",
    "E:/old/BBchannel/assets/drop/b/item.png", r"E:\old\assets\drop\b\item.png",
    "DROP/B/ITEM.PNG",
])
def test_drop_template_resolution_prefers_configured_directory(tmp_path, configured):
    _image(tmp_path / "assets", "drop/a/item.png")
    _image(tmp_path / "assets", "drop/b/item.png", "blue")
    resources = ResourceService(tmp_path / "assets", tmp_path / "data")
    assert _resolve_drop_template(resources, configured) == "drop/b/item.png"


@pytest.mark.parametrize("configured", ["item.png", "C:/images/item.png", r"C:\images\item.png"])
def test_legacy_drop_filename_fallback_requires_unique_candidate(tmp_path, configured):
    _image(tmp_path / "assets", "drop/a/item.png")
    resources = ResourceService(tmp_path / "assets", tmp_path / "data")
    assert _resolve_drop_template(resources, configured) == "drop/a/item.png"
    _image(tmp_path / "assets", "drop/b/item.png", "blue")
    resources.refresh_template_index()
    assert _resolve_drop_template(resources, configured) is None


@pytest.mark.parametrize("configured", [
    None, {}, 1, "", "  ", "drop/missing/item.png", "assets/drop/missing/item.png",
    "drop/../a/item.png", "drop/a/../../item.png", "drop/a/item.png\x00",
])
def test_invalid_or_missing_explicit_drop_path_does_not_choose_other_image(tmp_path, configured):
    _image(tmp_path / "assets", "drop/a/item.png")
    resources = ResourceService(tmp_path / "assets", tmp_path / "data")
    assert _resolve_drop_template(resources, configured) is None


def test_drop_resolution_does_not_stop_at_two_hundred_substring_matches(tmp_path):
    assets = tmp_path / "assets"
    for index in range(205):
        _image(assets, f"drop/a{index:03}/prefix-item.png")
    _image(assets, "drop/z/item.png")
    resources = ResourceService(assets, tmp_path / "data")
    assert _resolve_drop_template(resources, "C:/images/item.png") == "drop/z/item.png"


def test_drop_catalog_resolves_legacy_selection_and_preview_only_reads_drop_images(tmp_path):
    client = _client(tmp_path)
    assets = tmp_path / "assets"
    _image(assets, "drop/a/item.jpg", "blue")
    _image(assets, "battle/private.png")
    catalog = client.get("/api/drop-templates", params={"configured": r"E:\old\assets\drop\a\item.jpg"})
    assert catalog.status_code == 200
    assert catalog.json() == {"templates": ["drop/a/item.jpg"], "resolved_path": "drop/a/item.jpg"}
    preview = client.get("/api/drop-templates/image", params={"path": "drop/a/item.jpg"})
    assert preview.status_code == 200
    assert preview.headers["content-type"] == "image/png"
    with Image.open(BytesIO(preview.content)) as image:
        assert image.size == (32, 40)
        assert image.convert("RGB").getpixel((0, 0))[2] > 200
    for path in ("battle/private.png", "drop/../battle/private.png", "../outside.png", "drop/missing.png"):
        assert client.get("/api/drop-templates/image", params={"path": path}).status_code == 404


def test_drop_catalog_rejects_ambiguous_legacy_names_and_preserves_exact_choice(tmp_path):
    client = _client(tmp_path)
    assets = tmp_path / "assets"
    _image(assets, "drop/a/item.png")
    _image(assets, "drop/b/item.png")
    assert client.get("/api/drop-templates", params={"configured": "item.png"}).json()["resolved_path"] is None
    assert client.get("/api/drop-templates", params={"configured": "drop/b/item.png"}).json()["resolved_path"] == "drop/b/item.png"


def test_drop_resolution_and_preview_reject_symlink_escape(tmp_path):
    client = _client(tmp_path)
    assets = tmp_path / "assets"
    outside = _image(tmp_path, "outside.png")
    link = assets / "drop" / "linked.png"
    link.parent.mkdir(parents=True)
    link.symlink_to(outside)
    assert _resolve_drop_template(client.app.state.resources, "drop/linked.png") is None
    assert client.get("/api/drop-templates/image", params={"path": "drop/linked.png"}).status_code == 404


def test_removed_indexed_drop_template_is_not_resolved(tmp_path):
    assets = tmp_path / "assets"
    path = _image(assets, "drop/item.png")
    resources = ResourceService(assets, tmp_path / "data")
    assert _resolve_drop_template(resources, "drop/item.png") == "drop/item.png"
    path.unlink()
    assert _resolve_drop_template(resources, "drop/item.png") is None


@pytest.mark.parametrize("directory_link", [False, True])
def test_drop_preview_rejects_links_to_other_asset_directories(tmp_path, directory_link):
    client = _client(tmp_path)
    assets = tmp_path / "assets"
    outside = _image(assets, "battle/private.png", "blue")
    link = assets / "drop" / ("linked-dir" if directory_link else "linked.png")
    link.parent.mkdir(parents=True)
    link.symlink_to(outside.parent if directory_link else outside, target_is_directory=directory_link)
    path = "drop/linked-dir/private.png" if directory_link else "drop/linked.png"
    assert client.get("/api/drop-templates/image", params={"path": path}).status_code == 404


def test_cached_drop_replaced_with_link_to_other_asset_directory_is_not_resolved(tmp_path):
    assets = tmp_path / "assets"
    path = _image(assets, "drop/item.png")
    outside = _image(assets, "battle/private.png")
    resources = ResourceService(assets, tmp_path / "data")
    assert _resolve_drop_template(resources, "drop/item.png") == "drop/item.png"
    path.unlink()
    path.symlink_to(outside)
    assert _resolve_drop_template(resources, "drop/item.png") is None
