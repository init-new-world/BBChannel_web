from io import BytesIO
import json
from pathlib import Path

import pytest
from PIL import Image

from tests.test_api import _client


def _image(assets, name, color="red"):
    path = assets / name
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (64, 64), color).save(path)
    return path


def _catalog(tmp_path, entries=None):
    (tmp_path / "data" / "master_info.json").write_text(json.dumps(entries if entries is not None else {
        "A Default": {"SN": 0}, "B Combat": {"SN": 7}, "C Travel": {"SN": "008"},
        "Z duplicate": {"SN": "7"},
    }))


@pytest.mark.parametrize("equip,name", [("0", "A Default"), ("7", "B Combat"), ("008", "C Travel")])
@pytest.mark.parametrize("sex,color", [(0, "red"), (1, "blue")])
def test_master_portrait_uses_catalog_identity_and_original_gender_suffix(tmp_path, equip, name, sex, color):
    client = _client(tmp_path)
    _catalog(tmp_path)
    _image(tmp_path / "assets", f"masterface/{name}_{sex}.png", color)
    _image(tmp_path / "assets", f"masterface/Z duplicate_{sex}.png", "green")
    response = client.get("/api/masters/image", params={"equip": equip, "sex": sex})
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.headers["cache-control"] == "no-store"
    with Image.open(BytesIO(response.content)) as image:
        assert image.size == (64, 64)
        assert image.mode == "RGBA"
        assert image.getpixel((0, 0)) == ((255, 0, 0, 255) if sex == 0 else (0, 0, 255, 255))


def test_master_portrait_defaults_to_original_zero_gender_without_changing_data(tmp_path):
    client = _client(tmp_path)
    _catalog(tmp_path)
    _image(tmp_path / "assets", "masterface/A Default_0.png")
    before = (tmp_path / "data" / "master_info.json").read_bytes()
    assert client.get("/api/masters/image", params={"equip": "0"}).status_code == 200
    assert (tmp_path / "data" / "master_info.json").read_bytes() == before
    assert not (tmp_path / "data" / "settings").exists()


@pytest.mark.parametrize("equip", ["", "unknown", "8", "../private", "C:/private.png", "A Default"])
def test_unknown_master_ids_never_fall_back_to_names_or_another_outfit(tmp_path, equip):
    client = _client(tmp_path)
    _catalog(tmp_path)
    _image(tmp_path / "assets", "masterface/A Default_0.png")
    assert client.get("/api/masters/image", params={"equip": equip}).status_code == 404


@pytest.mark.parametrize("sex", ["-1", "2", "true", "female", ""])
def test_master_portrait_rejects_invalid_gender_parameters(tmp_path, sex):
    client = _client(tmp_path)
    _catalog(tmp_path)
    _image(tmp_path / "assets", "masterface/A Default_0.png")
    assert client.get("/api/masters/image", params={"equip": "0", "sex": sex}).status_code == 422


@pytest.mark.parametrize("name", ["../battle/private", "nested/private", r"..\battle\private", "C:private", "bad\x00name"])
def test_master_portrait_rejects_catalog_names_with_path_components(tmp_path, name):
    client = _client(tmp_path)
    _catalog(tmp_path, {name: {"SN": 7}})
    _image(tmp_path / "assets", "battle/private_0.png", "blue")
    assert client.get("/api/masters/image", params={"equip": "7"}).status_code == 404


@pytest.mark.parametrize("inside_assets", [False, True])
def test_master_portrait_rejects_file_symlinks_outside_its_directory(tmp_path, inside_assets):
    client = _client(tmp_path)
    _catalog(tmp_path)
    target = _image(tmp_path / "assets" if inside_assets else tmp_path, "private_0.png")
    link = tmp_path / "assets" / "masterface" / "A Default_0.png"
    link.parent.mkdir()
    link.symlink_to(target)
    assert client.get("/api/masters/image", params={"equip": "0"}).status_code == 404


def test_master_portrait_rejects_replaced_directory_link(tmp_path):
    client = _client(tmp_path)
    _catalog(tmp_path)
    _image(tmp_path / "assets", "private/A Default_0.png")
    (tmp_path / "assets" / "masterface").symlink_to(tmp_path / "assets" / "private", target_is_directory=True)
    assert client.get("/api/masters/image", params={"equip": "0"}).status_code == 404


def test_missing_or_corrupt_master_portrait_never_selects_another_gender(tmp_path):
    client = _client(tmp_path)
    _catalog(tmp_path)
    assets = tmp_path / "assets"
    _image(assets, "masterface/A Default_1.png", "blue")
    assert client.get("/api/masters/image", params={"equip": "0", "sex": 0}).status_code == 404
    (assets / "masterface" / "A Default_0.png").write_bytes(b"not an image")
    response = client.get("/api/masters/image", params={"equip": "0", "sex": 0})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "template_load_failed"


def test_removed_or_replaced_portrait_is_rechecked_on_every_read(tmp_path):
    client = _client(tmp_path)
    _catalog(tmp_path)
    path = _image(tmp_path / "assets", "masterface/A Default_0.png")
    assert client.get("/api/masters/image", params={"equip": "0"}).status_code == 200
    path.unlink()
    assert client.get("/api/masters/image", params={"equip": "0"}).status_code == 404
    target = _image(tmp_path / "assets", "battle/private.png", "blue")
    path.symlink_to(target)
    assert client.get("/api/masters/image", params={"equip": "0"}).status_code == 404


@pytest.mark.parametrize("sn,equip", [(False, "False"), (None, "None"), (1.5, "1.5")])
def test_malformed_first_catalog_id_cannot_fall_through_to_duplicate(tmp_path, sn, equip):
    client = _client(tmp_path)
    _catalog(tmp_path, {"A invalid": {"SN": sn}, "Z duplicate": {"SN": equip}})
    _image(tmp_path / "assets", "masterface/A invalid_0.png")
    _image(tmp_path / "assets", "masterface/Z duplicate_0.png", "blue")
    assert client.get("/api/masters/image", params={"equip": equip}).status_code == 404


def test_missing_first_portrait_does_not_select_duplicate_or_stale_catalog_entry(tmp_path):
    client = _client(tmp_path)
    _catalog(tmp_path)
    _image(tmp_path / "assets", "masterface/Z duplicate_0.png", "blue")
    assert client.get("/api/masters/image", params={"equip": "7"}).status_code == 404
    _catalog(tmp_path, {"New outfit": {"SN": 7}})
    _image(tmp_path / "assets", "masterface/New outfit_0.png")
    assert client.get("/api/masters/image", params={"equip": "7"}).status_code == 200


@pytest.mark.parametrize("sex", [0, 1])
def test_bundled_master_preview_uses_actual_portrait_not_outfit_thumbnail(sex):
    from webapp.services.master_portraits import MasterPortraitService
    from webapp.services.resources import ResourceService
    from webapp.services.script_data import ScriptDataService

    root = Path(__file__).resolve().parents[1]
    resources = ResourceService(root / "assets", root / "data")
    scripts = ScriptDataService(root / "data")
    name = next(item["name"] for item in scripts.list_masters()["masters"] if str(item["sn"]) == "0")
    output = MasterPortraitService(resources, scripts).read_image("0", sex)
    with Image.open(BytesIO(output)) as actual, Image.open(root / "assets" / "masterface" / f"{name}_{sex}.png") as source:
        assert actual.size == (256, 256)
        assert actual.mode == "RGBA"
        assert actual.tobytes() == source.convert("RGBA").tobytes()
