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
        {"type": "tap", "role": "servant_skill_5", "x": 474, "y": 590},
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
            "wait_after_seconds": 1.0,
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
        {"type": "condition_start", "execute_when_matched": True, "check_cards": True},
        None,
        {"type": "condition_end"},
    ]


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
        {"type": "tap", "role": "master_skill_menu", "x": 1131, "y": 320, "wait_after_seconds": 1.5},
        {"type": "tap", "role": "master_skill_12", "x": 1020, "y": 310, "wait_after_seconds": 1.0},
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
                {"type": "tap", "role": "servant_skill_2", "x": 163, "y": 590, "wait_after_seconds": 1.0},
                {"type": "tap", "role": "Kukulkan_option_1", "x": 960, "y": 423},
                {"type": "tap", "role": "skill_target_3", "x": 970, "y": 440},
            ],
        ),
        (
            ["Barghest", 3, 0],
            [
                {"type": "tap", "role": "servant_skill_3", "x": 256, "y": 590, "wait_after_seconds": 1.0},
                {"type": "tap", "role": "Barghest_option_0", "x": 640, "y": 423},
            ],
        ),
        (
            ["Soujyuro", 3, "B"],
            [
                {"type": "tap", "role": "servant_skill_3", "x": 256, "y": 590, "wait_after_seconds": 1.0},
                {"type": "tap", "role": "Soujyuro_option_B", "x": 1000, "y": 422},
            ],
        ),
        (
            ["BBDubai", 3, 0],
            [
                {"type": "tap", "role": "servant_skill_3", "x": 256, "y": 590, "wait_after_seconds": 1.0},
                {"type": "tap", "role": "BBDubai_option_0", "x": 483, "y": 390},
            ],
        ),
        (
            ["Hakuno", 3, "R"],
            [
                {"type": "tap", "role": "servant_skill_3", "x": 256, "y": 590, "wait_after_seconds": 1.0},
                {"type": "tap", "role": "Hakuno_option_R", "x": 1000, "y": 422},
            ],
        ),
        (
            ["VanGoghMiner", 1, "B"],
            [
                {"type": "tap", "role": "servant_skill_1", "x": 70, "y": 590, "wait_after_seconds": 1.0},
                {"type": "tap", "role": "VanGoghMiner_option_B", "x": 1000, "y": 422},
            ],
        ),
        (
            ["Dante", 2, "A"],
            [
                {"type": "tap", "role": "servant_skill_2", "x": 163, "y": 590, "wait_after_seconds": 1.0},
                {"type": "tap", "role": "Dante_option_A", "x": 640, "y": 423},
            ],
        ),
        (
            ["Gyokuto", 2, "One"],
            [
                {"type": "tap", "role": "servant_skill_2", "x": 163, "y": 590, "wait_after_seconds": 1.0},
                {"type": "tap", "role": "Gyokuto_option_One", "x": 960, "y": 423},
            ],
        ),
        (
            ["Charlotte", 3, "暴"],
            [
                {"type": "tap", "role": "servant_skill_3", "x": 256, "y": 590, "wait_after_seconds": 1.0},
                {"type": "tap", "role": "Charlotte_option_暴", "x": 767, "y": 422},
            ],
        ),
        (
            ["Flora", 3, "D"],
            [
                {"type": "tap", "role": "servant_skill_3", "x": 256, "y": 590, "wait_after_seconds": 1.0},
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
                {"type": "tap", "role": "servant_skill_1", "x": 70, "y": 590, "wait_after_seconds": 1.0},
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
                    "wait_after_seconds": 1.0,
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
            "x": 1131,
            "y": 320,
            "wait_after_seconds": 1.5,
        },
        {"type": "tap", "role": "master_skill_11", "x": 940, "y": 310},
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
