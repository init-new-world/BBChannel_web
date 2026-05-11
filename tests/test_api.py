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


def test_templates_route(tmp_path: Path):
    client = _client(tmp_path)
    assets = Path(client.app.state.resources.assets_dir)
    (assets / "assist").mkdir()
    (assets / "assist" / "icon.png").write_bytes(b"png")

    response = client.get("/api/templates")

    assert response.status_code == 200
    assert response.json() == {"templates": ["assist/icon.png"]}


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
