from pathlib import Path
from importlib.util import find_spec

import pytest

FASTAPI_AVAILABLE = find_spec("fastapi") is not None
pytestmark = pytest.mark.skipif(not FASTAPI_AVAILABLE, reason="FastAPI is not installed")

if FASTAPI_AVAILABLE:
    from fastapi.testclient import TestClient
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
    return TestClient(app)


def test_health_route(tmp_path: Path):
    response = _client(tmp_path).get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_capabilities_route(tmp_path: Path):
    response = _client(tmp_path).get("/api/capabilities")

    assert response.status_code == 200
    assert response.json()["capabilities"][0]["name"] == "fake"


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
