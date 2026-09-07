import base64
from io import BytesIO
from urllib.parse import quote

import pytest
from PIL import Image, ImageDraw

from tests.test_api import _client, _strategy_payload, _write_json


def _png(image):
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _encoded(image):
    return base64.b64encode(_png(image)).decode("ascii")


def _import(client, label="Badge", kind="command"):
    name = f"[{label}]W1280H720DXL10DXR30DYT20DYB40CON805.png"
    response = client.post(f"/api/{kind}-tags/import", json={
        "name": name, "image_base64": _encoded(Image.new("RGB", (20, 20), "blue")),
    })
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize("size,rotation", [((1280, 720), False), ((1920, 1080), False), ((1600, 720), False), ((720, 1280), True)])
def test_command_tag_capture_normalizes_rotation_and_letterboxing(tmp_path, size, rotation):
    client = _client(tmp_path)
    screen = Image.new("RGB", (1280, 720), "black")
    ImageDraw.Draw(screen).rectangle((45, 360, 75, 400), fill="red")
    if rotation:
        screen = screen.transpose(Image.Transpose.ROTATE_90)
    elif size == (1600, 720):
        wide = Image.new("RGB", size, "blue")
        wide.paste(screen, (160, 0))
        screen = wide
    else:
        screen = screen.resize(size)
    response = client.post("/api/command-tags/candidates", json={"screenshot_base64": _encoded(screen)})
    assert response.status_code == 200
    result = response.json()
    assert result["candidate_count"] == 5
    assert result["candidates"][0] == {"slot": 1, "anchor": [40, 353], "bounds": [40, 353, 193, 260]}
    assert result["candidates"][-1] == {"slot": 5, "anchor": [1067, 353], "bounds": [1067, 353, 193, 260]}
    normalized = Image.open(BytesIO(base64.b64decode(result["screenshot_base64"])))
    assert normalized.size == (1280, 720)
    assert normalized.getpixel((60, 380))[0] > 240


def test_command_tag_build_crop_inventory_preview_and_delete(tmp_path):
    client = _client(tmp_path)
    screen = Image.new("RGB", (1280, 720), "black")
    ImageDraw.Draw(screen).rectangle((306, 370, 325, 399), fill="red")
    response = client.post("/api/command-tags", json={
        "label": "Mark", "slot": 2, "bounds": [306, 370, 326, 400],
        "screenshot_base64": _encoded(screen), "threshold": 0.805,
    })
    assert response.status_code == 200, response.text
    tag = response.json()
    assert tag["name"] == "[Mark]W1280H720DXL10DXR30DYT17DYB47CON805.png"
    assert tag["template_path"] == f"battle/customCommandCard/{tag['name']}"
    assert tag["offsets"] == [10, 17, 30, 47]
    assert client.get("/api/command-tags").json() == {"tags": [tag]}
    assert client.get("/api/assist-tags").json() == {"tags": []}
    path = f"/api/command-tags/{quote(tag['name'], safe='')}"
    preview = client.get(f"{path}/image")
    assert Image.open(BytesIO(preview.content)).getpixel((10, 10)) == (255, 0, 0)
    assert client.delete(path).status_code == 200
    assert client.get("/api/command-tags").json() == {"tags": []}


@pytest.mark.parametrize("slot,bounds", [(0, [40, 360, 60, 380]), (True, [40, 360, 60, 380]), (6, [40, 360, 60, 380]), (1, [39, 360, 60, 380]), (1, [40, 340, 60, 380]), (1, [40, 360, 234, 380]), (1, [40, 360, 60, 614])])
def test_command_tag_build_rejects_invalid_slot_and_outside_card_crop(tmp_path, slot, bounds):
    client = _client(tmp_path)
    response = client.post("/api/command-tags", json={
        "label": "Invalid", "slot": slot, "bounds": bounds,
        "screenshot_base64": _encoded(Image.new("RGB", (1280, 720), "red")),
    })
    assert response.status_code in {400, 422}, response.text
    assert client.get("/api/command-tags").json() == {"tags": []}


def test_command_tag_import_checks_dimensions_and_conflicts(tmp_path):
    client = _client(tmp_path)
    tag = _import(client)
    request = {"name": tag["name"], "image_base64": _encoded(Image.new("RGB", (20, 20), "red"))}
    assert client.post("/api/command-tags/import", json=request).status_code == 409
    assert client.post("/api/command-tags/import", json={**request, "overwrite": True}).status_code == 200
    request["image_base64"] = _encoded(Image.new("RGB", (21, 20), "red"))
    assert client.post("/api/command-tags/import", json={**request, "overwrite": True}).status_code == 400


def test_command_tag_bind_is_idempotent_and_unbind_preserves_indices(tmp_path):
    client = _client(tmp_path)
    tags = [_import(client, label) for label in ("First", "Second")]
    _write_json(tmp_path / "data/settings/demo.json", {"server": "CH", "custom": {"value": 4}})
    for index, tag in enumerate(tags):
        response = client.put("/api/settings/demo/command-tags", json={"tag_name": tag["name"], "bound": True})
        assert response.status_code == 200, response.text
        assert response.json()["command_tag_binding"] == {"bound": True, "code": f"S{index}"}
    assert client.put("/api/settings/demo/command-tags", json={"tag_name": tags[0]["name"], "bound": True}).json()["command_tag_binding"]["code"] == "S0"
    original = client.get("/api/settings/demo").json()["config"]
    assert original["specialKeys"] == [tag["template_path"] for tag in tags]
    assert original["custom"] == {"value": 4}
    response = client.put("/api/settings/demo/command-tags", json={"tag_name": tags[0]["name"], "bound": False})
    assert response.status_code == 409
    assert "last" in response.json()["error"]["message"]
    assert client.get("/api/settings/demo").json()["config"] == original
    for tag in reversed(tags):
        response = client.put("/api/settings/demo/command-tags", json={"tag_name": tag["name"], "bound": False})
        assert response.status_code == 200, response.text
    assert client.get("/api/settings/demo").json()["config"]["specialKeys"] == []


@pytest.mark.parametrize("field,code", [("round1_turn0_strategy", "S0"), ("round1_extraStrategy", "2BS0")])
def test_command_tag_unbind_blocks_embedded_strategy_reference(tmp_path, field, code):
    client = _client(tmp_path)
    tag = _import(client)
    strategy = _strategy_payload()
    strategy["card2"]["cards"] = [code]
    config = {"server": "CH", "specialKeys": [tag["template_path"]], field: [strategy]}
    _write_json(tmp_path / "data/settings/demo.json", config)
    response = client.put("/api/settings/demo/command-tags", json={"tag_name": tag["name"], "bound": False})
    assert response.status_code == 409
    assert response.json()["error"]["details"]["code"] == "S0"
    assert client.get("/api/settings/demo").json()["config"] == config


def test_command_tag_delete_checks_legacy_list_paths_and_unreadable_scripts(tmp_path):
    client = _client(tmp_path)
    tag = _import(client)
    _write_json(tmp_path / "data/servant_info_CH.json", {})
    _write_json(tmp_path / "data/settings/legacy.json", {
        "server": "CH", "specialKeys": [[f"D:\\old\\assets\\battle\\customCommandCard\\{tag['name']}", "2B"]],
    })
    path = f"/api/command-tags/{quote(tag['name'], safe='')}"
    response = client.delete(path)
    assert response.status_code == 409
    assert response.json()["error"]["details"]["settings"] == ["legacy"]
    plan = client.get("/api/settings/legacy/plan").json()
    assert plan["special_keys"][0]["template_path"] == tag["template_path"]
    (tmp_path / "data/settings/legacy.json").write_text("broken")
    assert client.delete(path).status_code == 409
    assert client.get(f"{path}/image").status_code == 200


def test_command_tag_bind_rejects_missing_asset_without_changing_script(tmp_path):
    client = _client(tmp_path)
    config = {"server": "CH"}
    _write_json(tmp_path / "data/settings/demo.json", config)
    response = client.put("/api/settings/demo/command-tags", json={
        "tag_name": "[Missing]W1280H720DXL10DXR30DYT20DYB40CON8.png", "bound": True,
    })
    assert response.status_code == 404
    assert client.get("/api/settings/demo").json()["config"] == config


@pytest.mark.parametrize("link_level", ["file", "directory", "parent"])
def test_command_tag_storage_rejects_symbolic_links(tmp_path, link_level):
    client = _client(tmp_path)
    name = "[Linked]W1280H720DXL10DXR30DYT20DYB40CON8.png"
    outside = tmp_path / "outside"
    outside.mkdir()
    original = _png(Image.new("RGB", (20, 20), "red"))
    target = outside / name
    target.write_bytes(original)
    directory = tmp_path / "assets/battle/customCommandCard"
    if link_level == "file":
        directory.mkdir(parents=True)
        (directory / name).symlink_to(target)
    elif link_level == "directory":
        directory.parent.mkdir()
        directory.symlink_to(outside, target_is_directory=True)
    else:
        (outside / "customCommandCard").mkdir()
        (outside / "customCommandCard" / name).write_bytes(original)
        directory.parent.symlink_to(outside, target_is_directory=True)
    assert client.get("/api/command-tags").json() == {"tags": []}
    path = f"/api/command-tags/{quote(name, safe='')}"
    assert client.get(f"{path}/image").status_code == 400
    assert client.delete(path).status_code == 400
    response = client.post("/api/command-tags/import", json={
        "name": name, "image_base64": base64.b64encode(original).decode("ascii"), "overwrite": True,
    })
    assert response.status_code == 400
    assert target.read_bytes() == original


def test_command_tag_unbind_distinguishes_exact_tag_index(tmp_path):
    client = _client(tmp_path)
    tag = _import(client)
    strategy = _strategy_payload()
    strategy["card2"]["cards"] = ["S01"]
    _write_json(tmp_path / "data/settings/demo.json", {
        "server": "CH", "specialKeys": [tag["template_path"]], "round1_turn0_strategy": [strategy],
    })
    response = client.put("/api/settings/demo/command-tags", json={"tag_name": tag["name"], "bound": False})
    assert response.status_code == 200
    assert response.json()["config"]["round1_turn0_strategy"] == [strategy]


@pytest.mark.parametrize("kind,operation", [("command", "binding"), ("command", "setting_save"), ("assist", "setting_save")])
def test_tag_delete_is_atomic_with_script_writes(tmp_path, monkeypatch, kind, operation):
    from concurrent.futures import ThreadPoolExecutor, TimeoutError
    from threading import Event

    client = _client(tmp_path)
    tag = _import(client, kind=kind)
    _write_json(tmp_path / "data/settings/demo.json", {"server": "CH"})
    scripts = client.app.state.script_data
    scan_finished, resume_delete, write_started = Event(), Event(), Event()
    scan_method = f"find_{kind}_tag_references"
    original_scan = getattr(scripts, scan_method)

    def paused_scan(name):
        references = original_scan(name)
        scan_finished.set()
        assert resume_delete.wait(10)
        return references

    def write_script():
        write_started.set()
        if operation == "binding":
            return client.put("/api/settings/demo/command-tags", json={"tag_name": tag["name"], "bound": True})
        return client.put("/api/settings/demo", json={
            "config": {"server": "CH", ("specialKeys" if kind == "command" else "assistTags"): [tag["template_path"]]}, "overwrite": True,
        })

    monkeypatch.setattr(scripts, scan_method, paused_scan)
    with ThreadPoolExecutor(max_workers=2) as pool:
        deletion = pool.submit(client.delete, f"/api/{kind}-tags/{quote(tag['name'], safe='')}")
        try:
            assert scan_finished.wait(10)
            writing = pool.submit(write_script)
            assert write_started.wait(10)
            try:
                writing.result(timeout=0.5)
            except TimeoutError:
                pass
        finally:
            resume_delete.set()
        assert deletion.result(timeout=10).status_code == 200
        response = writing.result(timeout=10)
    assert response.status_code == (404 if operation == "binding" else 400), response.text
    assert client.get("/api/settings/demo").json()["config"] == {"server": "CH"}
