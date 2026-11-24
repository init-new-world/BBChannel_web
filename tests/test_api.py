from pathlib import Path
from importlib.util import find_spec

import pytest

FASTAPI_AVAILABLE = find_spec("fastapi") is not None
pytestmark = pytest.mark.skipif(not FASTAPI_AVAILABLE, reason="FastAPI is not installed")

if FASTAPI_AVAILABLE:
    from fastapi.testclient import TestClient
    from tests.test_client import create_test_client
else:
    TestClient = object

from webapp.core.models import Capability, DeviceInfo
from webapp.services.devices import DeviceService
from webapp.services.event_log import EventLog


def _write_json(path: Path, payload: object) -> None:
    import json

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _strategy_payload() -> dict:
    return {
        "card1": {"type": 0, "cards": [1], "criticalStar": 0, "more_or_less": True},
        "card2": {"type": 1, "cards": ["1B"], "criticalStar": 0, "more_or_less": True},
        "card3": {"type": 2, "cards": [], "criticalStar": 0, "more_or_less": True},
        "breakpoint": [False, False],
        "colorFirst": True,
    }


class FakeBackend:
    name = "fake"

    def capability(self):
        return Capability(name=self.name, available=True)

    def list_devices(self):
        return []


class FakeAdbBackend(FakeBackend):
    name = "adb"

    def __init__(self) -> None:
        self.requested_endpoint: str | None = None

    def connect_endpoint(self, endpoint: str) -> DeviceInfo:
        self.requested_endpoint = endpoint
        return DeviceInfo(
            backend="adb",
            device_id="172.25.208.1:16384",
            name="Xiaomi 24031PN0DC",
            status="device",
            source="adb-manual",
        )


def _client(tmp_path: Path, device_service: DeviceService | None = None) -> TestClient:
    from webapp.app import create_app

    assets = tmp_path / "assets"
    data = tmp_path / "data"
    assets.mkdir()
    data.mkdir()
    event_log = EventLog()
    device_service = device_service or DeviceService([FakeBackend()], event_log)
    app = create_app(
        assets_dir=assets,
        data_dir=data,
        device_service=device_service,
        event_log=event_log,
        runtime_db_path=tmp_path / "runtime.db",
    )
    return create_test_client(app)


def test_health_route(tmp_path: Path):
    response = _client(tmp_path).get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_app_lifespan_closes_device_service(tmp_path: Path):
    from webapp.app import create_app

    class ClosableBackend(FakeBackend):
        def __init__(self) -> None:
            self.close_calls = 0

        def close(self) -> None:
            self.close_calls += 1

    backend = ClosableBackend()
    event_log = EventLog()
    service = DeviceService([backend], event_log)
    app = create_app(
        assets_dir=tmp_path / "assets",
        data_dir=tmp_path / "data",
        device_service=service,
        event_log=event_log,
        runtime_db_path=tmp_path / "runtime.db",
    )
    Path(app.state.resources.assets_dir).mkdir()
    Path(app.state.resources.data_dir).mkdir()

    with create_test_client(app) as client:
        assert client.get("/api/health").status_code == 200

    assert backend.close_calls == 1


def test_capabilities_route(tmp_path: Path):
    response = _client(tmp_path).get("/api/capabilities")

    assert response.status_code == 200
    assert response.json()["capabilities"][0]["name"] == "fake"


def test_device_diagnostics_route(tmp_path: Path):
    response = _client(tmp_path).get("/api/device-diagnostics")

    assert response.status_code == 200
    assert response.json() == {
        "diagnostics": [{"backend": "fake", "available": True, "reason": None}]
    }


def test_connect_channels_route_preserves_capture_and_control_state(tmp_path: Path):
    class ConnectedBackend(FakeBackend):
        def list_devices(self):
            return [DeviceInfo(backend="fake", device_id="fake-1", name="Fake Device")]

    client = _client(
        tmp_path,
        DeviceService([ConnectedBackend()], EventLog()),
    )

    response = client.post(
        "/api/connect/channels",
        json={
            "capture_backend": "fake",
            "capture_device_id": "fake-1",
            "control_backend": "fake",
            "control_device_id": "fake-1",
        },
    )

    assert response.status_code == 200
    assert response.json()["capture"]["device_id"] == "fake-1"
    assert response.json()["control"]["device_id"] == "fake-1"


def test_templates_route(tmp_path: Path):
    client = _client(tmp_path)
    assets = Path(client.app.state.resources.assets_dir)
    (assets / "assist").mkdir()
    (assets / "assist" / "icon.png").write_bytes(b"png")

    response = client.get("/api/templates")

    assert response.status_code == 200
    assert response.json() == {"templates": ["assist/icon.png"]}


def test_template_index_and_metadata_routes(tmp_path: Path):
    client = _client(tmp_path)
    assets = Path(client.app.state.resources.assets_dir)
    template = assets / "battle" / "CH" / "target.png"
    template.parent.mkdir(parents=True)
    from PIL import Image

    Image.new("RGB", (12, 8), "red").save(template)

    index_response = client.get(
        "/api/template-index",
        params={"prefix": "battle/CH", "query": "TARGET", "limit": 10},
    )
    metadata_response = client.get("/api/template-metadata/battle/CH/target.png")

    assert index_response.status_code == 200
    assert index_response.json()["total"] == 1
    assert index_response.json()["entries"][0]["category"] == "battle"
    assert metadata_response.status_code == 200
    assert metadata_response.json()["width"] == 12
    assert metadata_response.json()["height"] == 8


def test_material_drop_catalog_and_query_routes(tmp_path: Path):
    client = _client(tmp_path)
    data = Path(client.app.state.resources.data_dir)
    _write_json(
        data / "material_quality.json",
        {"铜素材": ["英雄之证", "凶骨"], "银素材": ["世界树之种"]},
    )
    _write_json(
        data / "material_info.json",
        {
            "CH": {
                "铜素材": {
                    "英雄之证": [
                        {
                            "chapter": "第三特异点/关卡配置#自由关卡",
                            "section": "海盗船",
                            "AP": 18.9,
                            "P": "63.4%",
                        },
                        {
                            "chapter": "第一特异点/关卡配置#自由关卡",
                            "section": "马赛",
                            "AP": 20.3,
                            "P": "34.4%",
                        },
                    ]
                }
            },
            "JP": {},
        },
    )

    catalog_response = client.get("/api/material-drops/catalog")
    query_response = client.get(
        "/api/material-drops",
        params={"server": "ch", "quality": "铜素材", "material": "英雄之证"},
    )

    assert catalog_response.status_code == 200
    assert catalog_response.json() == {
        "servers": ["CH", "JP"],
        "qualities": [
            {"name": "铜素材", "materials": ["英雄之证", "凶骨"]},
            {"name": "银素材", "materials": ["世界树之种"]},
        ],
    }
    assert query_response.status_code == 200
    assert query_response.json() == {
        "server": "CH",
        "quality": "铜素材",
        "material": "英雄之证",
        "count": 2,
        "stages": [
            {
                "chapter": "第三特异点",
                "section": "海盗船",
                "average_ap": 18.9,
                "drop_rate": "63.4%",
                "drop_rate_percent": 63.4,
            },
            {
                "chapter": "第一特异点",
                "section": "马赛",
                "average_ap": 20.3,
                "drop_rate": "34.4%",
                "drop_rate_percent": 34.4,
            },
        ],
    }


def test_notebook_routes_persist_utf8_text(tmp_path: Path):
    client = _client(tmp_path)

    empty_response = client.get("/api/notebook")
    save_response = client.put(
        "/api/notebook",
        json={"content": "周回备忘\n苹果: 12\n"},
    )
    loaded_response = client.get("/api/notebook")

    assert empty_response.status_code == 200
    assert empty_response.json() == {"content": "", "bytes": 0}
    assert save_response.status_code == 200
    assert save_response.json() == {
        "content": "周回备忘\n苹果: 12\n",
        "bytes": len("周回备忘\n苹果: 12\n".encode("utf-8")),
    }
    assert loaded_response.json() == save_response.json()
    assert (Path(client.app.state.resources.data_dir) / "notice.txt").read_text(
        encoding="utf-8"
    ) == "周回备忘\n苹果: 12\n"


def test_equip_template_routes_build_and_move_precise_template(tmp_path: Path):
    import base64
    from io import BytesIO

    from PIL import Image

    client = _client(tmp_path)
    assets = Path(client.app.state.resources.assets_dir)

    def encoded_image(color: tuple[int, int, int]) -> str:
        output = BytesIO()
        Image.new("RGB", (474, 136), color).save(output, format="PNG")
        return base64.b64encode(output.getvalue()).decode("ascii")

    create_response = client.post(
        "/api/equip-templates/Event%20CE",
        json={
            "full_image_base64": encoded_image((240, 180, 30)),
            "non_full_image_base64": encoded_image((30, 90, 180)),
        },
    )

    assert create_response.status_code == 200
    assert create_response.json() == {
        "name": "Event CE",
        "location": "archive",
        "precise": True,
        "image_path": "equipmaker/assist_equip_store/Event CE.png",
    }
    archive_image = assets / "equipmaker" / "assist_equip_store" / "Event CE.png"
    archive_full_check = assets / "equipmaker" / "equip_check_store" / "Event CE_1.png"
    archive_non_full_check = assets / "equipmaker" / "equip_check_store" / "Event CE_0.png"
    assert Image.open(archive_image).size == (237, 68)
    assert Image.open(archive_full_check).size == (34, 34)
    assert Image.open(archive_non_full_check).size == (34, 34)

    preview_response = client.get(
        "/api/equip-templates/Event%20CE/image",
        params={"location": "archive"},
    )

    assert preview_response.status_code == 200
    assert preview_response.headers["content-type"] == "image/png"
    assert preview_response.headers["cache-control"] == "no-store"
    assert Image.open(BytesIO(preview_response.content)).size == (237, 68)

    activate_response = client.post("/api/equip-templates/Event%20CE/activate", json={})
    inventory_response = client.get("/api/equip-templates")

    assert activate_response.status_code == 200
    assert activate_response.json()["location"] == "active"
    assert inventory_response.status_code == 200
    assert inventory_response.json() == {
        "templates": [
            {
                "name": "Event CE",
                "location": "active",
                "precise": True,
                "image_path": "assist/assist_equip/Event CE.png",
            }
        ]
    }
    assert (assets / "assist" / "assist_equip" / "Event CE.png").is_file()
    assert (assets / "assist" / "equip_check" / "Event CE_1.png").is_file()
    assert not archive_image.exists()

    archive_response = client.post("/api/equip-templates/Event%20CE/archive", json={})

    assert archive_response.status_code == 200
    assert archive_response.json()["location"] == "archive"
    assert archive_image.is_file()
    assert archive_full_check.is_file()
    assert archive_non_full_check.is_file()


def test_equip_template_routes_reject_invalid_name_image_and_conflict(tmp_path: Path):
    import base64
    from io import BytesIO

    from PIL import Image

    client = _client(tmp_path)
    output = BytesIO()
    Image.new("RGB", (237, 68), "red").save(output, format="PNG")
    image_base64 = base64.b64encode(output.getvalue()).decode("ascii")

    invalid_name = client.post(
        "/api/equip-templates/bad%3Aname",
        json={"full_image_base64": image_base64},
    )
    invalid_image = client.post(
        "/api/equip-templates/Event%20CE",
        json={"full_image_base64": base64.b64encode(b"not an image").decode("ascii")},
    )
    first = client.post(
        "/api/equip-templates/Event%20CE",
        json={"full_image_base64": image_base64},
    )
    conflict = client.post(
        "/api/equip-templates/Event%20CE",
        json={"full_image_base64": image_base64},
    )

    assert invalid_name.status_code == 400
    assert invalid_name.json()["error"]["code"] == "data_file_invalid"
    assert invalid_image.status_code == 400
    assert invalid_image.json()["error"]["code"] == "data_file_invalid"
    assert first.status_code == 200
    assert first.json()["precise"] is False
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "data_file_conflict"


def test_equip_template_overwrite_removes_stale_precision_checks(tmp_path: Path):
    import base64
    from io import BytesIO

    from PIL import Image

    client = _client(tmp_path)
    assets = Path(client.app.state.resources.assets_dir)
    output = BytesIO()
    Image.new("RGB", (237, 68), "red").save(output, format="PNG")
    image_base64 = base64.b64encode(output.getvalue()).decode("ascii")

    precise = client.post(
        "/api/equip-templates/Event%20CE",
        json={
            "full_image_base64": image_base64,
            "non_full_image_base64": image_base64,
        },
    )
    activate_precise = client.post("/api/equip-templates/Event%20CE/activate", json={})
    simple = client.post(
        "/api/equip-templates/Event%20CE",
        json={"full_image_base64": image_base64},
    )
    activate_simple = client.post(
        "/api/equip-templates/Event%20CE/activate",
        json={"overwrite": True},
    )

    assert precise.status_code == 200
    assert activate_precise.status_code == 200
    assert simple.status_code == 200
    assert activate_simple.status_code == 200
    assert activate_simple.json()["precise"] is False
    assert not (assets / "assist" / "equip_check" / "Event CE_0.png").exists()
    assert not (assets / "assist" / "equip_check" / "Event CE_1.png").exists()


def test_equip_template_candidate_route_extracts_assist_row_regions(tmp_path: Path):
    import base64
    from io import BytesIO

    pytest.importorskip("cv2")
    from PIL import Image, ImageDraw

    client = _client(tmp_path)
    assets = Path(client.app.state.resources.assets_dir)
    data = Path(client.app.state.resources.data_dir)
    servant_faces = assets / "servantface"
    servant_faces.mkdir(parents=True)
    portrait = Image.new("RGB", (60, 60), (20, 35, 50))
    portrait_draw = ImageDraw.Draw(portrait)
    portrait_draw.rectangle((4, 4, 55, 55), outline=(50, 170, 230), width=4)
    portrait_draw.ellipse((15, 12, 44, 41), fill=(240, 210, 160))
    portrait_draw.line((8, 52, 52, 8), fill=(230, 40, 80), width=4)
    portrait.save(servant_faces / "Support_1.png")
    _write_json(
        data / "servant_info_CH.json",
        {"Support": {"SN": "314", "class": "Caster"}},
    )
    _write_json(
        data / "settings" / "demo.json",
        {
            "server": "CH",
            "servant_3_name": "Support",
            "assistIdx": 3,
            "assistMode": "从者礼装",
        },
    )
    screenshot = Image.new("RGB", (1280, 720), (18, 24, 32))
    screenshot.paste(portrait, (200, 180))
    screenshot_output = BytesIO()
    screenshot.save(screenshot_output, format="PNG")

    response = client.post(
        "/api/equip-templates/candidates",
        json={
            "setting_name": "demo",
            "screenshot_base64": base64.b64encode(screenshot_output.getvalue()).decode("ascii"),
            "threshold": 0.99,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["servant_name"] == "Support"
    assert payload["servant_match_count"] == 1
    assert payload["candidate_count"] == 4
    assert [candidate["kind"] for candidate in payload["candidates"]] == [
        "equip",
        "skill_1",
        "skill_2",
        "skill_3",
    ]
    for candidate in payload["candidates"]:
        image = Image.open(BytesIO(base64.b64decode(candidate["image_base64"])))
        assert image.size == (237, 68)


def test_assist_tag_candidate_route_returns_screenshot_and_servant_anchors(tmp_path: Path):
    import base64
    from io import BytesIO

    pytest.importorskip("cv2")
    from PIL import Image, ImageDraw

    client = _client(tmp_path)
    assets = Path(client.app.state.resources.assets_dir)
    data = Path(client.app.state.resources.data_dir)
    servant_faces = assets / "servantface"
    servant_faces.mkdir(parents=True)
    portrait = Image.new("RGB", (60, 60), (20, 35, 50))
    portrait_draw = ImageDraw.Draw(portrait)
    portrait_draw.rectangle((4, 4, 55, 55), outline=(50, 170, 230), width=4)
    portrait_draw.ellipse((15, 12, 44, 41), fill=(240, 210, 160))
    portrait_draw.line((8, 52, 52, 8), fill=(230, 40, 80), width=4)
    portrait.save(servant_faces / "Support_1.png")
    _write_json(
        data / "servant_info_CH.json",
        {"Support": {"SN": "314", "class": "Caster"}},
    )
    _write_json(
        data / "settings" / "demo.json",
        {
            "server": "CH",
            "servant_3_name": "Support",
            "assistIdx": 3,
            "assistMode": "从者礼装",
        },
    )
    screenshot = Image.new("RGB", (1280, 720), (18, 24, 32))
    screenshot.paste(portrait, (200, 180))
    screenshot_output = BytesIO()
    screenshot.save(screenshot_output, format="PNG")
    encoded = base64.b64encode(screenshot_output.getvalue()).decode("ascii")

    response = client.post(
        "/api/assist-tags/candidates",
        json={
            "setting_name": "demo",
            "screenshot_base64": encoded,
            "threshold": 0.99,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["servant_name"] == "Support"
    assert payload["candidate_count"] == 1
    assert payload["candidates"][0]["anchor"] == [230, 210]
    assert payload["candidates"][0]["bounds"] == [200, 180, 60, 60]
    assert base64.b64decode(payload["screenshot_base64"]) == screenshot_output.getvalue()


def test_assist_tag_routes_build_preview_list_and_delete(tmp_path: Path):
    import base64
    from io import BytesIO
    from urllib.parse import quote

    from PIL import Image, ImageDraw

    client = _client(tmp_path)
    screenshot = Image.new("RGB", (1280, 720), (18, 24, 32))
    ImageDraw.Draw(screenshot).rectangle((250, 120, 289, 149), fill=(220, 70, 135))
    screenshot_output = BytesIO()
    screenshot.save(screenshot_output, format="PNG")

    create_response = client.post(
        "/api/assist-tags",
        json={
            "label": "Guild",
            "screenshot_base64": base64.b64encode(screenshot_output.getvalue()).decode("ascii"),
            "anchor": [100, 95],
            "bounds": [250, 120, 290, 150],
            "threshold": 0.85,
        },
    )

    assert create_response.status_code == 200
    created = create_response.json()
    name = "[Guild]W1280H720DXL150DXR190DYT25DYB55CON85.png"
    assert created["name"] == name
    inventory_response = client.get("/api/assist-tags")
    assert inventory_response.status_code == 200
    assert inventory_response.json()["tags"] == [created]

    image_response = client.get(f"/api/assist-tags/{quote(name, safe='')}/image")
    assert image_response.status_code == 200
    assert Image.open(BytesIO(image_response.content)).size == (40, 30)

    delete_response = client.delete(f"/api/assist-tags/{quote(name, safe='')}")
    assert delete_response.status_code == 200
    assert delete_response.json() == {"name": name, "deleted": True}
    assert client.get("/api/assist-tags").json() == {"tags": []}


def test_assist_tag_cannot_be_deleted_while_referenced_by_a_script(tmp_path: Path):
    from io import BytesIO
    from urllib.parse import quote
    from PIL import Image

    client = _client(tmp_path)
    image = BytesIO()
    Image.new("RGB", (20, 20), "blue").save(image, format="PNG")
    name = "[Bound]W1280H720DXL0DXR20DYT0DYB20CON8.png"
    client.app.state.assist_tags.import_image(name, image.getvalue())
    _write_json(tmp_path / "data" / "servant_info_CH.json", {})
    for script, path in (("first", f"assist/assist_tags/{name}"), ("legacy", f"D:\\old\\{name}")):
        _write_json(tmp_path / "data" / "settings" / f"{script}.json", {
            "server": "CH", "assistTags": [path],
        })

    response = client.delete(f"/api/assist-tags/{quote(name, safe='')}")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "data_file_conflict"
    assert response.json()["error"]["details"]["settings"] == ["first", "legacy"]
    assert len(client.get("/api/assist-tags").json()["tags"]) == 1
    for script in ("first", "legacy"):
        response = client.put(f"/api/settings/{script}", json={
            "config": {"server": "CH", "assistTags": []}, "overwrite": True,
        })
        assert response.status_code == 200
    assert client.delete(f"/api/assist-tags/{quote(name, safe='')}").status_code == 200


@pytest.mark.parametrize("tag,code", [
    ("broken.png", "invalid_assist_tags"),
    ("[Missing]W1280H720DXL0DXR20DYT0DYB20CON8.png", "missing_assist_tag"),
])
def test_setting_program_reports_invalid_assist_tags_without_server_error(tmp_path: Path, tag, code):
    client = _client(tmp_path)
    _write_json(tmp_path / "data" / "servant_info_CH.json", {})
    _write_json(tmp_path / "data" / "settings" / "invalid-tag.json", {
        "server": "CH", "assistTags": [tag],
        "round1_turns": 1, "round1_turn1_skill": "1",
    })

    response = client.get("/api/settings/invalid-tag/program")

    assert response.status_code == 200
    program = response.json()
    assert program["validation"]["ok"] is False
    assert code in {error["code"] for error in program["validation"]["errors"]}
    assert program["execution"]["battle"]["ready"] is False


@pytest.mark.parametrize("image_state,code", [
    ("missing", "missing_special_key"), ("wrong_size", "invalid_special_key_image"),
    ("invalid", "invalid_special_keys"),
])
def test_setting_program_rejects_invalid_special_keys(tmp_path: Path, image_state, code):
    from PIL import Image

    client = _client(tmp_path)
    name = "[Key]W1280H720DXL0DXR20DYT0DYB20CON01.png"
    if image_state == "wrong_size":
        directory = tmp_path / "assets" / "special_keys"
        directory.mkdir()
        Image.new("RGB", (19, 20), "blue").save(directory / name)
    if image_state == "invalid":
        name = "broken.png"
    _write_json(tmp_path / "data" / "servant_info_CH.json", {})
    _write_json(tmp_path / "data" / "settings" / "invalid-key.json", {
        "server": "CH", "specialKeys": [name], "round1_turns": 1,
    })
    response = client.get("/api/settings/invalid-key/program")
    assert response.status_code == 200
    program = response.json()
    assert not program["validation"]["ok"]
    assert code in {error["code"] for error in program["validation"]["errors"]}
    assert not program["execution"]["battle"]["ready"]


def test_setting_accepts_valid_special_key_image(tmp_path: Path):
    from PIL import Image

    client = _client(tmp_path)
    name = "[Key]W1280H720DXL-10DXR10DYT-20DYB20CON01.png"
    directory = tmp_path / "assets" / "special_keys"
    directory.mkdir()
    Image.new("RGB", (20, 40), "blue").save(directory / name)
    _write_json(tmp_path / "data" / "servant_info_CH.json", {})
    response = client.put("/api/settings/key", json={"config": {"server": "CH", "specialKeys": [name]}})
    assert response.status_code == 200
    plan = client.get("/api/settings/key/plan").json()
    assert plan["validation"]["ok"]
    assert plan["special_keys"][0]["threshold"] == 0.01


def test_setting_rejects_tag_image_with_wrong_dimensions(tmp_path: Path):
    from PIL import Image

    client = _client(tmp_path)
    name = "[Wrong]W1280H720DXL0DXR20DYT0DYB20CON8.png"
    directory = tmp_path / "assets" / "assist" / "assist_tags"
    directory.mkdir(parents=True)
    Image.new("RGB", (19, 20), "blue").save(directory / name)
    _write_json(tmp_path / "data" / "servant_info_CH.json", {})

    response = client.put("/api/settings/wrong-size", json={
        "config": {"server": "CH", "assistTags": [name]},
    })

    assert response.status_code == 400
    errors = response.json()["error"]["details"]["validation"]["errors"]
    assert errors[0]["code"] == "invalid_assist_tag_image"


def test_equip_template_test_route_reports_precise_limit_break_match(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    import base64
    import random
    from io import BytesIO

    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    from PIL import Image

    client = _client(tmp_path)
    randomizer = random.Random(37)
    full = Image.new("RGB", (237, 68))
    full.putdata(
        [
            (
                randomizer.randrange(256),
                randomizer.randrange(256),
                randomizer.randrange(256),
            )
            for _ in range(237 * 68)
        ]
    )
    non_full = full.copy()
    non_full.paste(Image.new("RGB", (34, 34), "black"), (194, 34))

    def encoded(image: Image.Image) -> str:
        output = BytesIO()
        image.save(output, format="PNG")
        return base64.b64encode(output.getvalue()).decode("ascii")

    create_response = client.post(
        "/api/equip-templates/Event%20CE",
        json={
            "full_image_base64": encoded(full),
            "non_full_image_base64": encoded(non_full),
        },
    )
    screenshot = Image.new("RGB", (1280, 720), (18, 24, 32))
    scale = 2 / 3
    main = Image.fromarray(
        cv2.resize(
            np.asarray(full.crop((39, 0, 194, 56))),
            (round(155 * scale), round(56 * scale)),
            interpolation=cv2.INTER_AREA,
        )
    )
    check = Image.fromarray(
        cv2.resize(
            np.asarray(full.crop((194, 34, 228, 68))),
            (round(34 * scale), round(34 * scale)),
            interpolation=cv2.INTER_AREA,
        )
    )
    screenshot.paste(main, (126, 250))
    screenshot.paste(check, (229, 273))
    decode_calls = 0
    original_decode = cv2.imdecode

    def count_decode(*args, **kwargs):
        nonlocal decode_calls
        decode_calls += 1
        return original_decode(*args, **kwargs)

    monkeypatch.setattr(cv2, "imdecode", count_decode)

    response = client.post(
        "/api/equip-templates/Event%20CE/test",
        json={
            "location": "archive",
            "screenshot_base64": encoded(screenshot),
            "threshold": 0.99,
        },
    )

    assert create_response.status_code == 200
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["name"] == "Event CE"
    assert payload["location"] == "archive"
    assert payload["precise"] is True
    assert payload["match_count"] == 1
    assert payload["matches"][0]["top_left"] == [126, 250]
    assert payload["matches"][0]["full_limit_break"] is True
    assert payload["matches"][0]["limit_break_method"] == "precise"
    assert decode_calls == 2


def test_match_route_accepts_roi_and_scales(tmp_path: Path):
    pytest.importorskip("cv2")
    import base64
    from io import BytesIO
    from PIL import Image, ImageDraw

    client = _client(tmp_path)
    assets = Path(client.app.state.resources.assets_dir)
    template = Image.new("RGB", (10, 10), "black")
    draw = ImageDraw.Draw(template)
    draw.rectangle((1, 1, 8, 8), outline="white")
    draw.line((1, 8, 8, 1), fill="red", width=2)
    template.save(assets / "target.png")
    screenshot = Image.new("RGB", (80, 60), "black")
    screenshot.paste(template, (45, 25))
    output = BytesIO()
    screenshot.save(output, format="PNG")

    response = client.post(
        "/api/match",
        json={
            "screenshot_base64": base64.b64encode(output.getvalue()).decode("ascii"),
            "template_path": "target.png",
            "threshold": 0.8,
            "roi": [40, 20, 30, 25],
            "scales": [1.0],
        },
    )

    assert response.status_code == 200
    assert response.json()["top_left"] == [45, 25]
    assert response.json()["roi"] == [40, 20, 30, 25]
    assert response.json()["scale"] == 1.0


def test_batch_match_route_returns_candidates_in_request_order(tmp_path: Path):
    pytest.importorskip("cv2")
    import base64
    from io import BytesIO
    from PIL import Image, ImageDraw

    client = _client(tmp_path)
    assets = Path(client.app.state.resources.assets_dir)
    screenshot = Image.new("RGB", (80, 60), "black")
    for name, position, color in [
        ("first.png", (10, 15), "red"),
        ("second.png", (50, 30), "green"),
    ]:
        template = Image.new("RGB", (10, 10), "black")
        draw = ImageDraw.Draw(template)
        draw.rectangle((1, 1, 8, 8), outline="white")
        draw.line((1, 8, 8, 1), fill=color, width=2)
        template.save(assets / name)
        screenshot.paste(template, position)
    output = BytesIO()
    screenshot.save(output, format="PNG")

    response = client.post(
        "/api/match/batch",
        json={
            "screenshot_base64": base64.b64encode(output.getvalue()).decode("ascii"),
            "candidates": [
                {"template_path": "second.png", "threshold": 0.8},
                {"template_path": "first.png", "threshold": 0.8},
            ],
        },
    )

    assert response.status_code == 200
    assert [match["template_path"] for match in response.json()["matches"]] == [
        "second.png",
        "first.png",
    ]


def test_match_debug_route_returns_png_overlay(tmp_path: Path):
    pytest.importorskip("cv2")
    import base64
    from io import BytesIO
    from PIL import Image, ImageDraw

    client = _client(tmp_path)
    assets = Path(client.app.state.resources.assets_dir)
    template = Image.new("RGB", (10, 10), "black")
    draw = ImageDraw.Draw(template)
    draw.rectangle((1, 1, 8, 8), outline="white")
    draw.line((1, 8, 8, 1), fill="red", width=2)
    template.save(assets / "target.png")
    screenshot = Image.new("RGB", (80, 60), "black")
    screenshot.paste(template, (45, 25))
    screenshot_bytes = BytesIO()
    screenshot.save(screenshot_bytes, format="PNG")

    response = client.post(
        "/api/match/debug",
        json={
            "screenshot_base64": base64.b64encode(screenshot_bytes.getvalue()).decode("ascii"),
            "template_path": "target.png",
            "threshold": 0.8,
            "roi": [40, 20, 30, 25],
            "scales": [1.0],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["result"]["top_left"] == [45, 25]
    overlay = base64.b64decode(payload["overlay_base64"], validate=True)
    with Image.open(BytesIO(overlay)) as image:
        assert image.format == "PNG"
        assert image.size == (80, 60)


def test_settings_routes_expose_data_dir_configs(tmp_path: Path):
    client = _client(tmp_path)
    data = Path(client.app.state.resources.data_dir)
    _write_json(data / "servant_info_CH.json", {"Servant A": {"other_name": []}})
    _write_json(
        data / "settings" / "demo.json",
        {
            "server": "CH",
            "servant_0_name": "Servant A",
            "round1_turns": 1,
            "round1_turn0_strategy": [_strategy_payload()],
        },
    )

    list_response = client.get("/api/settings")
    detail_response = client.get("/api/settings/demo")

    assert list_response.status_code == 200
    assert list_response.json() == {"settings": [{"name": "demo", "path": "settings/demo.json"}]}
    assert detail_response.status_code == 200
    assert detail_response.json()["summary"]["strategy_count"] == 1
    assert detail_response.json()["validation"]["ok"] is True


def test_setting_plan_route_exposes_normalized_actions(tmp_path: Path):
    client = _client(tmp_path)
    data = Path(client.app.state.resources.data_dir)
    _write_json(data / "servant_info_CH.json", {"Servant A": {"other_name": []}})
    _write_json(
        data / "settings" / "demo.json",
        {
            "server": "CH",
            "servant_0_name": "Servant A",
            "round1_turns": 1,
            "round1_turn0_skill": [1],
            "round1_turn0_np": [1],
        },
    )

    response = client.get("/api/settings/demo/plan")

    assert response.status_code == 200
    payload = response.json()
    assert payload["name"] == "demo"
    assert payload["rounds"][0]["turns"][0]["actions"] == [
        {"type": "skill", "command": 1},
        {"type": "np", "servant": 1},
    ]
    assert payload["summary"]["action_count"] == 2


def test_setting_program_compiles_no_chain_np_turn_to_dynamic_selection(tmp_path: Path):
    client = _client(tmp_path)
    data = Path(client.app.state.resources.data_dir)
    _write_json(data / "servant_info_CH.json", {"Servant A": {"other_name": []}})
    _write_json(
        data / "settings" / "demo.json",
        {
            "server": "CH",
            "servant_0_name": "Servant A",
            "noChain": 1,
            "round1_turns": 1,
            "round1_turn0_np": [1],
        },
    )

    response = client.get("/api/settings/demo/program")

    assert response.status_code == 200
    command_phase = response.json()["rounds"][0]["turns"][0]["command_phase"]
    assert command_phase == {
        "supported": True,
        "steps": [
            {"type": "tap", "role": "attack", "x": 1150, "y": 600},
            {
                "type": "strategy",
                "role": "command_card_no_chain",
                "strategies": [],
                "preselected_nps": [1],
                "avoid_chain": True,
                "selection_count": 3,
            },
        ],
        "reason": None,
    }


def test_setting_program_route_compiles_skill_targets_and_np_to_logical_taps(tmp_path: Path):
    client = _client(tmp_path)
    data = Path(client.app.state.resources.data_dir)
    _write_json(data / "servant_info_CH.json", {"Servant A": {"other_name": []}})
    _write_json(
        data / "settings" / "demo.json",
        {
            "server": "CH",
            "servant_0_name": "Servant A",
            "round1_turns": 1,
            "round1_turn0_skill": [1, [5, 2]],
            "round1_turn0_np": [3],
        },
    )

    response = client.get("/api/settings/demo/program")

    assert response.status_code == 200
    payload = response.json()
    assert payload["summary"] == {
        "action_count": 3,
        "supported_action_count": 3,
        "unsupported_action_count": 0,
        "tap_count": 4,
        "execution_tap_count": 7,
        "extra_action_count": 0,
        "extra_tap_count": 4,
    }
    assert payload["execution"] == {
        "skills": {
            "ready": False,
            "reason": "Program contains non-skill actions.",
        },
        "battle": {"ready": True, "reason": None},
    }
    actions = payload["rounds"][0]["turns"][0]["actions"]
    assert actions[0]["steps"] == [
        {"type": "tap", "role": "servant_skill_1", "x": 70, "y": 590},
    ]
    assert actions[1]["steps"] == [
        {
            "type": "tap",
            "role": "servant_skill_5",
            "x": 474,
            "y": 590,
            "wait_after_seconds": 0.5,
        },
        {"type": "tap", "role": "skill_target_2", "x": 640, "y": 440},
    ]
    assert actions[2]["steps"] == [
        {"type": "tap", "role": "np_3", "x": 870, "y": 200},
    ]
    assert payload["rounds"][0]["turns"][0]["command_phase"] == {
        "supported": True,
        "steps": [
            {"type": "tap", "role": "attack", "x": 1150, "y": 600},
            {"type": "tap", "role": "np_3", "x": 870, "y": 200},
            {"type": "tap", "role": "face_card_1", "x": 150, "y": 500},
            {"type": "tap", "role": "face_card_2", "x": 375, "y": 500},
        ],
        "reason": None,
    }


def test_setting_program_is_not_ready_when_script_validation_fails(tmp_path: Path):
    client = _client(tmp_path)
    data = Path(client.app.state.resources.data_dir)
    _write_json(data / "servant_info_CH.json", {})
    _write_json(
        data / "settings" / "invalid-watchdog.json",
        {
            "server": "CH",
            "stuckRestart": 1,
            "checkStuckInterval": 0,
            "round1_turns": 1,
            "round1_turn0_skill": [1],
        },
    )

    response = client.get("/api/settings/invalid-watchdog/program")

    assert response.status_code == 200
    assert response.json()["validation"]["ok"] is False
    assert response.json()["execution"]["battle"] == {
        "ready": False,
        "reason": "Script validation failed.",
    }


def test_setting_program_compiles_runtime_card_strategy(tmp_path: Path):
    client = _client(tmp_path)
    data = Path(client.app.state.resources.data_dir)
    _write_json(data / "servant_info_CH.json", {"Servant A": {"other_name": []}})
    _write_json(
        data / "settings" / "strategy.json",
        {
            "server": "CH",
            "servant_0_name": "Servant A",
            "round1_turns": 1,
            "round1_turn0_strategy": [_strategy_payload()],
        },
    )

    response = client.get("/api/settings/strategy/program")

    assert response.status_code == 200
    payload = response.json()
    assert payload["execution"]["battle"] == {"ready": True, "reason": None}
    assert payload["rounds"][0]["turns"][0]["command_phase"] == {
        "supported": True,
        "steps": [
            {"type": "tap", "role": "attack", "x": 1150, "y": 600},
            {
                "type": "strategy",
                "role": "command_card_strategy",
                "strategies": [_strategy_payload()],
                "preselected_nps": [],
                "selection_count": 3,
            },
        ],
        "reason": None,
    }
    assert payload["summary"]["execution_tap_count"] == 4


def test_setting_program_compiles_strategy_that_requires_critical_stars(tmp_path: Path):
    client = _client(tmp_path)
    data = Path(client.app.state.resources.data_dir)
    _write_json(data / "servant_info_CH.json", {"Servant A": {"other_name": []}})
    strategy = _strategy_payload()
    strategy["card2"]["criticalStar"] = 5
    _write_json(
        data / "settings" / "stars.json",
        {
            "server": "CH",
            "servant_0_name": "Servant A",
            "round1_turns": 1,
            "round1_turn0_strategy": [strategy],
        },
    )

    payload = client.get("/api/settings/stars/program").json()

    assert payload["execution"]["battle"] == {"ready": True, "reason": None}
    command_phase = payload["rounds"][0]["turns"][0]["command_phase"]
    assert command_phase["supported"] is True
    assert command_phase["steps"][1]["strategies"][0]["card2"]["criticalStar"] == 5


def test_setting_program_compiles_post_turn_servant_replacements(tmp_path: Path):
    client = _client(tmp_path)
    data = Path(client.app.state.resources.data_dir)
    _write_json(data / "servant_info_CH.json", {"Servant A": {"other_name": []}})
    _write_json(
        data / "settings" / "replace.json",
        {
            "server": "CH",
            "servant_0_name": "Servant A",
            "round1_turns": 1,
            "round1_turn0_replace": {"1": 4, "4": None},
        },
    )

    payload = client.get("/api/settings/replace/program").json()

    assert payload["execution"]["battle"] == {"ready": True, "reason": None}
    action = payload["rounds"][0]["turns"][0]["actions"][0]
    assert action == {
        "source": {"type": "replace", "replacements": {"1": 4, "4": None}},
        "supported": True,
        "steps": [],
        "reason": None,
    }
    assert payload["summary"]["execution_tap_count"] == 4


def test_setting_program_compiles_servant_special_skill_choice(tmp_path: Path):
    client = _client(tmp_path)
    data = Path(client.app.state.resources.data_dir)
    _write_json(data / "servant_info_CH.json", {"Space": {"other_name": []}})
    _write_json(
        data / "settings" / "special.json",
        {
            "server": "CH",
            "servant_0_name": "Space",
            "round1_turns": 1,
            "round1_turn0_skill": [[-2, 2]],
        },
    )

    payload = client.get("/api/settings/special/program").json()

    assert payload["execution"]["battle"] == {"ready": True, "reason": None}
    assert payload["rounds"][0]["turns"][0]["actions"][0]["steps"] == [
        {
            "type": "tap",
            "role": "servant_skill_2",
            "x": 163,
            "y": 590,
            "wait_after_seconds": 0.5,
        },
        {"type": "tap", "role": "special_skill_option_2", "x": 639, "y": 433},
    ]


def test_setting_program_compiles_command_spell_np_charge(tmp_path: Path):
    client = _client(tmp_path)
    data = Path(client.app.state.resources.data_dir)
    _write_json(data / "servant_info_CH.json", {"Servant A": {"other_name": []}})
    _write_json(
        data / "settings" / "command-spell.json",
        {
            "server": "CH",
            "servant_0_name": "Servant A",
            "round1_turns": 1,
            "round1_turn0_skill": [["令咒·宝具解放", 1]],
        },
    )

    payload = client.get("/api/settings/command-spell/program").json()

    assert payload["execution"]["battle"] == {"ready": True, "reason": None}
    assert payload["rounds"][0]["turns"][0]["actions"][0]["steps"] == [
        {"type": "tap", "role": "command_spell_menu", "x": 1060, "y": 82, "wait_after_seconds": 1.0},
        {"type": "tap", "role": "command_spell_np_charge", "x": 637, "y": 343, "wait_after_seconds": 1.0},
        {"type": "tap", "role": "command_spell_confirm", "x": 793, "y": 430, "wait_after_seconds": 1.0},
        {"type": "tap", "role": "command_spell_target_1", "x": 350, "y": 440},
    ]


def test_setting_program_compiles_conditional_skill_block_controls(tmp_path: Path):
    client = _client(tmp_path)
    data = Path(client.app.state.resources.data_dir)
    _write_json(data / "servant_info_CH.json", {"Servant A": {"other_name": []}})
    condition = [_strategy_payload()]
    _write_json(
        data / "settings" / "condition.json",
        {
            "server": "CH",
            "servant_0_name": "Servant A",
            "round1_turns": 1,
            "round1_turn0_skill": [["Start", 1, [1]], 1, ["End"]],
            "round1_turn0_condition": condition,
        },
    )

    payload = client.get("/api/settings/condition/program").json()

    assert payload["execution"]["battle"] == {"ready": True, "reason": None}
    turn = payload["rounds"][0]["turns"][0]
    assert turn["condition"] == condition
    assert [action.get("control") for action in turn["actions"]] == [
        {"type": "condition_start", "execute_when_matched": True, "check_cards": True, "checks": [1]},
        None,
        {"type": "condition_end"},
    ]


def test_setting_program_compiles_four_field_np_conditional_skills(tmp_path: Path):
    client = _client(tmp_path)
    data = Path(client.app.state.resources.data_dir)
    _write_json(data / "servant_info_CH.json", {"Servant A": {"other_name": []}})
    _write_json(
        data / "settings" / "np-condition.json",
        {
            "server": "CH",
            "servant_0_name": "Servant A",
            "round1_turns": 1,
            "round1_turn0_skill": [
                ["Start", 1, [], ["np", [1, "≥", 50], [0, "≥", 50], [1, "≤", 100]]],
                1,
                ["End"],
            ],
        },
    )

    payload = client.get("/api/settings/np-condition/program").json()

    assert payload["execution"]["battle"] == {"ready": True, "reason": None}
    turn = payload["rounds"][0]["turns"][0]
    assert [action.get("control") for action in turn["actions"]] == [
        {
            "type": "condition_start",
            "execute_when_matched": True,
            "check_cards": False,
            "checks": [],
            "check_np": True,
            "np_checks": [
                {"servant": 1, "enabled": True, "operator": "≥", "value": 50},
                {"servant": 2, "enabled": False, "operator": "≥", "value": 50},
                {"servant": 3, "enabled": True, "operator": "≤", "value": 100},
            ],
        },
        None,
        {"type": "condition_end"},
    ]


@pytest.mark.parametrize(
    "bad_np_spec",
    [
        "np",
        ["other", [1, "≥", 50], [0, "≥", 50], [0, "≥", 50]],
        ["np", [1, "≥", 50], [0, "≥", 50]],
        ["np", [2, "≥", 50], [0, "≥", 50], [0, "≥", 50]],
        ["np", [1, ">", 50], [0, "≥", 50], [0, "≥", 50]],
        ["np", [1, "≥", -1], [0, "≥", 50], [0, "≥", 50]],
        ["np", [1, "≥", 301], [0, "≥", 50], [0, "≥", 50]],
        ["np", [1, "≥", True], [0, "≥", 50], [0, "≥", 50]],
    ],
)
def test_setting_program_rejects_malformed_four_field_np_condition(
    tmp_path: Path,
    bad_np_spec,
):
    client = _client(tmp_path)
    data = Path(client.app.state.resources.data_dir)
    _write_json(data / "servant_info_CH.json", {"Servant A": {"other_name": []}})
    _write_json(
        data / "settings" / "bad-np-condition.json",
        {
            "server": "CH",
            "servant_0_name": "Servant A",
            "round1_turns": 1,
            "round1_turn0_skill": [
                ["Start", 1, [], bad_np_spec],
                1,
                ["End"],
            ],
        },
    )

    payload = client.get("/api/settings/bad-np-condition/program").json()

    assert payload["execution"]["battle"]["ready"] is False
    assert payload["rounds"][0]["turns"][0]["actions"][0]["supported"] is False


def test_setting_program_compiles_master_order_change(tmp_path: Path):
    client = _client(tmp_path)
    data = Path(client.app.state.resources.data_dir)
    _write_json(data / "servant_info_CH.json", {"Servant A": {"other_name": []}})
    _write_json(
        data / "settings" / "order-change.json",
        {
            "server": "CH",
            "servant_0_name": "Servant A",
            "round1_turns": 1,
            "round1_turn0_skill": [[12, 1, 4]],
        },
    )

    payload = client.get("/api/settings/order-change/program").json()

    assert payload["execution"]["battle"] == {"ready": True, "reason": None}
    action = payload["rounds"][0]["turns"][0]["actions"][0]
    assert action["state_change"] == {"type": "servant_exchange", "positions": [1, 4]}
    assert action["steps"] == [
        {"type": "tap", "role": "master_skill_menu", "x": 1217, "y": 320, "wait_after_seconds": 0.5},
        {"type": "tap", "role": "master_skill_12", "x": 1089, "y": 310, "wait_after_seconds": 0.7},
        {"type": "tap", "role": "exchange_position_1", "x": 137, "y": 352},
        {"type": "tap", "role": "exchange_position_4", "x": 737, "y": 352},
        {"type": "tap", "role": "exchange_confirm_1", "x": 607, "y": 625},
        {"type": "tap", "role": "exchange_confirm_2", "x": 607, "y": 625},
        {"type": "tap", "role": "exchange_confirm_3", "x": 607, "y": 625},
    ]


@pytest.mark.parametrize(
    ("command", "expected_steps"),
    [
        ([13, 5], [{"type": "tap", "role": "enemy_target_5", "x": 341, "y": 138}]),
        (
            ["令咒·灵基修复", 2],
            [
                {"type": "tap", "role": "command_spell_menu", "x": 1060, "y": 82, "wait_after_seconds": 1.0},
                {"type": "tap", "role": "command_spell_heal", "x": 637, "y": 523, "wait_after_seconds": 1.0},
                {"type": "tap", "role": "command_spell_confirm", "x": 793, "y": 430, "wait_after_seconds": 1.0},
                {"type": "tap", "role": "command_spell_target_2", "x": 640, "y": 440},
            ],
        ),
    ],
)
def test_setting_program_compiles_target_and_command_spell_heal(
    tmp_path: Path,
    command: list,
    expected_steps: list[dict],
):
    client = _client(tmp_path)
    data = Path(client.app.state.resources.data_dir)
    _write_json(data / "servant_info_CH.json", {"Servant A": {"other_name": []}})
    _write_json(
        data / "settings" / "utility.json",
        {
            "server": "CH",
            "servant_0_name": "Servant A",
            "round1_turns": 1,
            "round1_turn0_skill": [command],
        },
    )

    payload = client.get("/api/settings/utility/program").json()

    assert payload["execution"]["battle"] == {"ready": True, "reason": None}
    assert payload["rounds"][0]["turns"][0]["actions"][0]["steps"] == expected_steps


def test_setting_program_rejects_unhashable_skill_command_without_server_error(tmp_path: Path):
    client = _client(tmp_path)
    data = Path(client.app.state.resources.data_dir)
    _write_json(data / "servant_info_CH.json", {"Servant A": {"other_name": []}})
    _write_json(
        data / "settings" / "malformed.json",
        {
            "server": "CH",
            "servant_0_name": "Servant A",
            "round1_turns": 1,
            "round1_turn0_skill": [[["nested"], 1]],
        },
    )

    response = client.get("/api/settings/malformed/program")

    assert response.status_code == 200
    payload = response.json()
    assert payload["execution"]["battle"] == {
        "ready": False,
        "reason": "Program contains unsupported actions.",
    }


@pytest.mark.parametrize(
    ("command", "expected_steps"),
    [
        (
            ["Kukulkan", 2, 1, 3],
            [
                {"type": "tap", "role": "servant_skill_2", "x": 163, "y": 590, "wait_after_seconds": 0.5},
                {"type": "tap", "role": "Kukulkan_option_1", "x": 960, "y": 423},
                {"type": "tap", "role": "skill_target_3", "x": 970, "y": 440},
            ],
        ),
        (
            ["Barghest", 3, 0],
            [
                {"type": "tap", "role": "servant_skill_3", "x": 256, "y": 590, "wait_after_seconds": 0.5},
                {"type": "tap", "role": "Barghest_option_0", "x": 640, "y": 423},
            ],
        ),
        (
            ["Soujyuro", 3, "B"],
            [
                {"type": "tap", "role": "servant_skill_3", "x": 256, "y": 590, "wait_after_seconds": 0.5},
                {"type": "tap", "role": "Soujyuro_option_B", "x": 1000, "y": 422},
            ],
        ),
        (
            ["BBDubai", 3, 0],
            [
                {"type": "tap", "role": "servant_skill_3", "x": 256, "y": 590, "wait_after_seconds": 0.5},
                {"type": "tap", "role": "BBDubai_option_0", "x": 483, "y": 390},
            ],
        ),
        (
            ["Hakuno", 3, "R"],
            [
                {"type": "tap", "role": "servant_skill_3", "x": 256, "y": 590, "wait_after_seconds": 0.5},
                {"type": "tap", "role": "Hakuno_option_R", "x": 1000, "y": 422},
            ],
        ),
        (
            ["VanGoghMiner", 1, "B"],
            [
                {"type": "tap", "role": "servant_skill_1", "x": 70, "y": 590, "wait_after_seconds": 0.5},
                {"type": "tap", "role": "VanGoghMiner_option_B", "x": 1000, "y": 422},
            ],
        ),
        (
            ["Dante", 2, "A"],
            [
                {"type": "tap", "role": "servant_skill_2", "x": 163, "y": 590, "wait_after_seconds": 0.5},
                {"type": "tap", "role": "Dante_option_A", "x": 640, "y": 423},
            ],
        ),
        (
            ["Gyokuto", 2, "One"],
            [
                {"type": "tap", "role": "servant_skill_2", "x": 163, "y": 590, "wait_after_seconds": 0.5},
                {"type": "tap", "role": "Gyokuto_option_One", "x": 960, "y": 423},
            ],
        ),
        (
            ["Charlotte", 3, "暴"],
            [
                {"type": "tap", "role": "servant_skill_3", "x": 256, "y": 590, "wait_after_seconds": 0.5},
                {"type": "tap", "role": "Charlotte_option_暴", "x": 767, "y": 422},
            ],
        ),
        (
            ["Flora", 3, "D"],
            [
                {"type": "tap", "role": "servant_skill_3", "x": 256, "y": 590, "wait_after_seconds": 0.5},
                {"type": "tap", "role": "Flora_option_D", "x": 960, "y": 423},
            ],
        ),
    ],
)
def test_setting_program_compiles_named_servant_skill_options(
    tmp_path: Path,
    command: list,
    expected_steps: list[dict],
):
    client = _client(tmp_path)
    data = Path(client.app.state.resources.data_dir)
    _write_json(data / "servant_info_CH.json", {"Servant A": {"other_name": []}})
    _write_json(
        data / "settings" / "named-skill.json",
        {
            "server": "CH",
            "servant_0_name": "Servant A",
            "round1_turns": 1,
            "round1_turn0_skill": [command],
        },
    )

    payload = client.get("/api/settings/named-skill/program").json()

    assert payload["execution"]["battle"] == {"ready": True, "reason": None}
    assert payload["rounds"][0]["turns"][0]["actions"][0]["steps"] == expected_steps


@pytest.mark.parametrize(
    ("needs", "expected_steps", "expected_runtime"),
    [
        (
            [],
            [
                {"type": "tap", "role": "servant_skill_1", "x": 70, "y": 590, "wait_after_seconds": 0.5},
            ],
            None,
        ),
        (
            [["1B", "2A"], ["3Q"]],
            [],
            {
                "type": "hakuno_card_reroll",
                "need_cards": [["1B", "2A"], ["3Q"]],
                "skill_step": {
                    "type": "tap",
                    "role": "servant_skill_1",
                    "x": 70,
                    "y": 590,
                    "wait_after_seconds": 0.5,
                },
                "max_rerolls": 3,
            },
        ),
    ],
)
def test_setting_program_compiles_dynamic_hakuno_skill(
    tmp_path: Path,
    needs: list,
    expected_steps: list[dict],
    expected_runtime: dict | None,
):
    client = _client(tmp_path)
    data = Path(client.app.state.resources.data_dir)
    _write_json(data / "servant_info_CH.json", {"Servant A": {"other_name": []}})
    _write_json(
        data / "settings" / "hakuno-dynamic.json",
        {
            "server": "CH",
            "servant_0_name": "Servant A",
            "round1_turns": 1,
            "round1_turn0_skill": [["Hakuno", 1, needs]],
        },
    )

    payload = client.get("/api/settings/hakuno-dynamic/program").json()

    action = payload["rounds"][0]["turns"][0]["actions"][0]
    assert payload["execution"]["battle"] == {"ready": True, "reason": None}
    assert action["supported"] is True
    assert action["steps"] == expected_steps
    assert action.get("runtime") == expected_runtime


def test_setting_program_compiles_extra_turn_template(tmp_path: Path):
    client = _client(tmp_path)
    data = Path(client.app.state.resources.data_dir)
    _write_json(data / "servant_info_CH.json", {"Servant A": {"other_name": []}})
    strategy = [_strategy_payload()]
    _write_json(
        data / "settings" / "extra-turn.json",
        {
            "server": "CH",
            "servant_0_name": "Servant A",
            "round1_turns": 1,
            "round1_turn0_skill": [1],
            "round1_extraSkill": [7, [-2, 2], [11, 1]],
            "round1_extraStrategy": strategy,
        },
    )

    payload = client.get("/api/settings/extra-turn/program").json()

    extra_turn = payload["rounds"][0]["extra_turn"]
    assert payload["execution"]["battle"] == {"ready": True, "reason": None}
    skill_actions = [
        action
        for action in extra_turn["actions"]
        if action["source"]["type"] == "skill"
    ]
    assert [action["source"]["command"] for action in skill_actions] == [
        7,
        [-2, 2],
        [11, 1],
    ]
    assert all(action["supported"] for action in extra_turn["actions"])
    assert extra_turn["command_phase"]["steps"] == [
        {"type": "tap", "role": "attack", "x": 1150, "y": 600},
        {
            "type": "strategy",
            "role": "command_card_strategy",
            "strategies": strategy,
            "preselected_nps": [],
            "selection_count": 3,
        },
    ]
    assert payload["summary"]["extra_action_count"] == 4


def test_setting_program_uses_explicit_extra_condition_when_present(tmp_path: Path):
    client = _client(tmp_path)
    data = Path(client.app.state.resources.data_dir)
    _write_json(data / "servant_info_CH.json", {"Servant A": {"other_name": []}})
    turn_cond = [_strategy_payload()]
    extra_cond = [{**_strategy_payload(), "colorFirst": True}]
    _write_json(
        data / "settings" / "extra-cond.json",
        {
            "server": "CH",
            "servant_0_name": "Servant A",
            "round1_turns": 1,
            "round1_turn0_skill": [1],
            "round1_turn0_condition": turn_cond,
            "round1_extraSkill": [["Start", 1, [1]], 7, ["End"]],
            "round1_extraCondition": extra_cond,
        },
    )

    payload = client.get("/api/settings/extra-cond/program").json()
    extra_turn = payload["rounds"][0]["extra_turn"]
    assert extra_turn["condition"] == extra_cond
    assert extra_turn["actions"][0]["control"] == {
        "type": "condition_start",
        "execute_when_matched": True,
        "check_cards": True,
        "checks": [1],
    }
    assert extra_turn["actions"][2]["control"] == {"type": "condition_end"}


def test_setting_program_compiles_master_skill_menu_and_target(tmp_path: Path):
    client = _client(tmp_path)
    data = Path(client.app.state.resources.data_dir)
    _write_json(data / "servant_info_CH.json", {"Servant A": {"other_name": []}})
    _write_json(
        data / "settings" / "master.json",
        {
            "server": "CH",
            "servant_0_name": "Servant A",
            "round1_turns": 1,
            "round1_turn0_skill": [[11, 1]],
        },
    )

    response = client.get("/api/settings/master/program")

    assert response.status_code == 200
    payload = response.json()
    assert payload["execution"]["skills"] == {"ready": True, "reason": None}
    assert payload["rounds"][0]["turns"][0]["actions"][0]["steps"] == [
        {
            "type": "tap",
            "role": "master_skill_menu",
            "x": 1217,
            "y": 320,
            "wait_after_seconds": 0.5,
        },
        {
            "type": "tap",
            "role": "master_skill_11",
            "x": 997,
            "y": 310,
            "wait_after_seconds": 0.5,
        },
        {"type": "tap", "role": "skill_target_1", "x": 350, "y": 440},
    ]


def test_strategy_routes_expose_data_dir_presets(tmp_path: Path):
    client = _client(tmp_path)
    data = Path(client.app.state.resources.data_dir)
    _write_json(data / "strategy" / "brave.json", [{"tag": "brave", "strategy": _strategy_payload()}])

    list_response = client.get("/api/strategies")
    detail_response = client.get("/api/strategies/brave")

    assert list_response.status_code == 200
    assert list_response.json() == {"strategies": [{"name": "brave", "path": "strategy/brave.json"}]}
    assert detail_response.status_code == 200
    assert detail_response.json()["entries"][0]["tag"] == "brave"


def test_put_setting_creates_and_explicitly_overwrites_preset(tmp_path: Path):
    client = _client(tmp_path)
    config = {"server": "CH", "round1_turns": 0}

    created = client.put("/api/settings/demo", json={"config": config})
    conflict = client.put("/api/settings/demo", json={"config": config})
    overwritten = client.put(
        "/api/settings/demo",
        json={"config": {**config, "round1_turns": 1}, "overwrite": True},
    )

    assert created.status_code == 200
    assert created.json()["name"] == "demo"
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "data_file_conflict"
    assert overwritten.status_code == 200
    assert overwritten.json()["config"]["round1_turns"] == 1


def test_put_strategy_creates_validated_preset(tmp_path: Path):
    client = _client(tmp_path)
    entries = [{"tag": "brave", "strategy": _strategy_payload()}]

    created = client.put("/api/strategies/brave", json={"entries": entries})
    conflict = client.put("/api/strategies/brave", json={"entries": entries})
    invalid = client.put(
        "/api/strategies/broken",
        json={"entries": [{"tag": "broken", "strategy": {}}]},
    )

    assert created.status_code == 200
    assert created.json()["entries"] == entries
    assert conflict.status_code == 409
    assert invalid.status_code == 400
    assert invalid.json()["error"]["code"] == "data_file_invalid"


def test_delete_setting_and_strategy_routes(tmp_path: Path):
    client = _client(tmp_path)
    data = Path(client.app.state.resources.data_dir)
    _write_json(data / "settings" / "demo.json", {"server": "CH"})
    _write_json(data / "strategy" / "brave.json", [])

    setting = client.delete("/api/settings/demo")
    strategy = client.delete("/api/strategies/brave")
    missing = client.delete("/api/settings/demo")

    assert setting.status_code == 200
    assert setting.json()["deleted"] is True
    assert strategy.status_code == 200
    assert strategy.json()["deleted"] is True
    assert missing.status_code == 404


def test_servant_and_master_routes_expose_catalogs(tmp_path: Path):
    client = _client(tmp_path)
    data = Path(client.app.state.resources.data_dir)
    _write_json(data / "servant_info_CH.json", {"Servant A": {"other_name": ["A"], "SN": "100"}})
    _write_json(data / "master_info.json", {"Chaldea": {"SN": 7, "skill_name": ["Heal"]}})

    servants_response = client.get("/api/servants", params={"server": "CH"})
    masters_response = client.get("/api/masters")

    assert servants_response.status_code == 200
    assert servants_response.json()["servants"][0]["name"] == "Servant A"
    assert masters_response.status_code == 200
    assert masters_response.json()["masters"][0]["name"] == "Chaldea"


def test_servant_portrait_route_serves_face_image_and_exposes_star_metadata(tmp_path: Path):
    from PIL import Image

    client = _client(tmp_path)
    data = Path(client.app.state.resources.data_dir)
    assets = Path(client.app.state.resources.assets_dir)
    _write_json(
        data / "servant_info_CH.json",
        {"Hero": {"other_name": ["H"], "class": "Saber", "SN": "100100", "star": 5, "servant_face": 2}},
    )
    face_dir = assets / "servantface"
    face_dir.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (60, 60), (40, 80, 120)).save(face_dir / "Hero_2.png")

    catalog = client.get("/api/servants", params={"server": "CH"})
    assert catalog.status_code == 200
    entry = catalog.json()["servants"][0]
    assert entry["star"] == 5
    assert entry["face_index"] == 2

    img = client.get("/api/servants/image", params={"name": "Hero", "server": "CH"})
    assert img.status_code == 200
    assert img.content.startswith(b"\x89PNG\r\n\x1a\n")

    bad = client.get("/api/servants/image", params={"name": "../secret", "server": "CH"})
    assert bad.status_code == 404

    skill_dir = assets / "servant_skill"
    skill_dir.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (40, 40), (200, 150, 40)).save(skill_dir / "充能.png")
    icon = client.get("/api/skills/icon", params={"name": "充能"})
    assert icon.status_code == 200
    assert icon.content.startswith(b"\x89PNG\r\n\x1a\n")
    assert client.get("/api/skills/icon", params={"name": "../bad"}).status_code == 404


def test_tap_route_returns_structured_error_when_disconnected(tmp_path: Path):
    response = _client(tmp_path).post("/api/tap", json={"x": 10, "y": 20})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "device_not_connected"


def test_adb_connect_endpoint_route_returns_connected_device(tmp_path: Path):
    event_log = EventLog()
    backend = FakeAdbBackend()
    client = _client(tmp_path, DeviceService([backend], event_log))

    response = client.post("/api/adb/connect-endpoint", json={"endpoint": "172.25.208.1:16384"})

    assert response.status_code == 200
    assert response.json()["device"]["device_id"] == "172.25.208.1:16384"
    assert backend.requested_endpoint == "172.25.208.1:16384"


def test_match_route_returns_missing_template_error(tmp_path: Path):
    response = _client(tmp_path).post(
        "/api/match",
        json={"screenshot_base64": "", "template_path": "missing.png"},
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "template_not_found"


def test_screen_rotation_routes_get_and_post_calibration(tmp_path: Path):
    from webapp.devices.coordinates import FrameNormalizer

    unconfigured_dir = tmp_path / "unconfigured"
    configured_dir = tmp_path / "configured"
    unconfigured_dir.mkdir()
    configured_dir.mkdir()

    unconfigured = _client(unconfigured_dir)
    missing_normalizer = unconfigured.post("/api/screen/rotation", json={"steps": 1})
    assert missing_normalizer.status_code == 400
    assert missing_normalizer.json()["error"]["code"] == "screen_geometry_unavailable"

    client = _client(
        configured_dir,
        DeviceService([FakeBackend()], EventLog(), frame_normalizer=FrameNormalizer()),
    )

    initial = client.get("/api/screen/rotation")
    assert initial.status_code == 200
    assert initial.json()["rotation"] is None

    stepped = client.post("/api/screen/rotation", json={"steps": 1})
    assert stepped.status_code == 200
    assert stepped.json()["rotation"] == 90

    explicit = client.post("/api/screen/rotation", json={"rotation": 180})
    assert explicit.status_code == 200
    assert explicit.json()["rotation"] == 180

    reset = client.post("/api/screen/rotation", json={"rotation": None})
    assert reset.status_code == 200
    assert reset.json()["rotation"] is None

    invalid = client.post("/api/screen/rotation", json={"rotation": 45})
    assert invalid.status_code == 422

