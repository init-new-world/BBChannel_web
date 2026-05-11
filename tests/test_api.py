from pathlib import Path
from importlib.util import find_spec

import pytest

FASTAPI_AVAILABLE = find_spec("fastapi") is not None
pytestmark = pytest.mark.skipif(not FASTAPI_AVAILABLE, reason="FastAPI is not installed")

if FASTAPI_AVAILABLE:
    from fastapi.testclient import TestClient
else:
    TestClient = object

from webapp.core.models import Capability
from webapp.services.devices import DeviceService
from webapp.services.event_log import EventLog


class FakeBackend:
    name = "fake"

    def capability(self):
        return Capability(name=self.name, available=True)

    def list_devices(self):
        return []


def _client(tmp_path: Path) -> TestClient:
    from webapp.app import create_app

    assets = tmp_path / "assets"
    data = tmp_path / "data"
    assets.mkdir()
    data.mkdir()
    event_log = EventLog()
    device_service = DeviceService([FakeBackend()], event_log)
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


def test_match_route_returns_missing_template_error(tmp_path: Path):
    response = _client(tmp_path).post(
        "/api/match",
        json={"screenshot_base64": "", "template_path": "missing.png"},
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "template_not_found"
