import json
import os
import socket
import threading
import time
from io import BytesIO

import pytest
from PIL import Image, ImageDraw

playwright = pytest.importorskip("playwright.sync_api")
pytestmark = pytest.mark.skipif(
    not os.environ.get("BBCHANNEL_TEST_CHROMIUM"),
    reason="Set BBCHANNEL_TEST_CHROMIUM to a local Chromium executable.",
)


@pytest.fixture
def tag_console(tmp_path):
    import uvicorn

    from webapp.app import create_app
    from webapp.core.models import Capability, DeviceInfo
    from webapp.services.devices import DeviceService
    from webapp.services.event_log import EventLog

    assets = tmp_path / "assets"
    data = tmp_path / "data"
    (assets / "servantface").mkdir(parents=True)
    (data / "settings").mkdir(parents=True)
    portrait = Image.new("RGB", (60, 60), (30, 60, 95))
    draw = ImageDraw.Draw(portrait)
    draw.ellipse((8, 7, 52, 53), fill=(210, 95, 170))
    draw.line((5, 54, 54, 5), fill=(45, 225, 190), width=4)
    portrait.save(assets / "servantface" / "Support_1.png")
    screen = Image.new("RGB", (1280, 720), (36, 48, 65))
    screen.paste(portrait, (70, 65))
    ImageDraw.Draw(screen).text((250, 120), "Guild 314", fill="white")
    output = BytesIO()
    screen.save(output, format="PNG")
    (data / "servant_info_CH.json").write_text(json.dumps({
        "Support": {"SN": "314", "class": "Caster"},
    }))
    (data / "settings" / "demo.json").write_text(json.dumps({
        "server": "CH", "assistIdx": 3, "servant_3_name": "Support",
        "assistMode": "仅从者", "round1_turns": 0,
    }))

    class Backend:
        name = "fixture"

        def capability(self):
            return Capability(self.name, True)

        def list_devices(self):
            return [DeviceInfo(self.name, "test")]

        def snapshot(self, device_id):
            return output.getvalue()

    events = EventLog()
    devices = DeviceService([Backend()], events)
    devices.connect("fixture", "test")
    app = create_app(
        assets_dir=assets, data_dir=data, device_service=devices,
        runtime_db_path=tmp_path / "runtime.db",
    )
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(app, log_level="error"))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]})
        thread.start()
        try:
            deadline = time.monotonic() + 10
            while not server.started:
                if not thread.is_alive() or time.monotonic() > deadline:
                    pytest.fail("Test server failed to start")
                time.sleep(0.02)
            with playwright.sync_playwright() as driver:
                browser = driver.chromium.launch(
                    executable_path=os.environ["BBCHANNEL_TEST_CHROMIUM"],
                    headless=True, args=["--no-sandbox"],
                )
                try:
                    yield browser, f"http://127.0.0.1:{port}", tmp_path
                finally:
                    browser.close()
        finally:
            server.should_exit = True
            thread.join(timeout=10)
            assert not thread.is_alive()


@pytest.mark.parametrize("width,height", [(1440, 1000), (800, 1000), (390, 844)])
def test_tag_maker_creates_and_binds_a_crop_at_each_viewport(tag_console, width, height):
    browser, url, directory = tag_console
    page = browser.new_page(viewport={"width": width, "height": height})
    page.set_default_timeout(10000)
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(url)
    page.locator("#open-assist-tags").click()
    page.locator("#capture-assist-tag-screen").click()
    playwright.expect(page.locator("#assist-tag-maker-status")).to_have_text("1 supports matched")
    playwright.expect(page.locator("#assist-tag-canvas-empty")).to_be_hidden()
    if width <= 900:
        capture_box = page.locator(".assist-tag-capture").bounding_box()
        library_box = page.locator(".assist-tag-library").bounding_box()
        save_box = page.locator("#save-assist-tag").bounding_box()
        assert library_box["y"] >= capture_box["y"] + capture_box["height"]
        assert library_box["y"] >= save_box["y"] + save_box["height"]
    canvas = page.locator("#assist-tag-canvas")
    canvas.scroll_into_view_if_needed()
    box = canvas.bounding_box()
    start = (box["x"] + box["width"] * 250 / 1280, box["y"] + box["height"] * 120 / 720)
    end = (box["x"] + box["width"] * 350 / 1280, box["y"] + box["height"] * 160 / 720)
    page.mouse.move(*start)
    page.mouse.down()
    page.mouse.move(*end, steps=4)
    page.mouse.up()
    playwright.expect(page.locator("#assist-tag-crop-status")).to_have_text("250,120 -> 350,160")
    page.locator("#save-assist-tag").click()
    playwright.expect(page.locator("#assist-tag-maker-status")).to_have_text("Saved Custom")
    tag = page.request.get(f"{url}/api/assist-tags").json()["tags"][0]
    assert tag["image_size"] == [100, 40]
    assert tag["offsets"] == [150, 25, 250, 65]
    page.locator("#bind-assist-tag").click()
    playwright.expect(page.locator("#assist-tag-library-status")).to_have_text("Bound to script")
    detail = page.request.get(f"{url}/api/settings/demo").json()
    assert detail["config"]["assistTags"] == [tag["template_path"]]
    page.locator("#bind-assist-tag").click()
    playwright.expect(page.locator("#assist-tag-library-status")).to_have_text("Unbound from script")
    assert page.request.get(f"{url}/api/settings/demo").json()["config"]["assistTags"] == []
    page.locator(".assist-tag-form").evaluate("element => element.scrollTop = 0")
    page.screenshot(path=str(directory / f"tag-maker-{width}.png"))
    assert page.locator(".assist-tag-form").evaluate("e => e.scrollWidth <= e.clientWidth")
    assert canvas.evaluate("e => Array.from(e.getContext('2d').getImageData(250, 120, 100, 40).data).some(v => v > 100)")
    assert errors == []
    page.close()
