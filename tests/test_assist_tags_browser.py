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
    page.locator("#assist-tag-threshold").fill("0.805")
    page.locator("#save-assist-tag").click()
    playwright.expect(page.locator("#assist-tag-maker-status")).to_have_text("Saved Custom")
    tag = page.request.get(f"{url}/api/assist-tags").json()["tags"][0]
    assert tag["image_size"] == [100, 40]
    assert tag["offsets"] == [150, 25, 250, 65]
    assert tag["threshold"] == 0.805
    playwright.expect(page.locator("#assist-tag-metadata")).to_contain_text("threshold 0.805")
    page.locator("#bind-assist-tag").click()
    playwright.expect(page.locator("#assist-tag-library-status")).to_have_text("Bound to script")
    detail = page.request.get(f"{url}/api/settings/demo").json()
    assert detail["config"]["assistTags"] == [tag["template_path"]]
    page.once("dialog", lambda dialog: dialog.accept())
    page.locator("#delete-assist-tag").click()
    playwright.expect(page.locator("#assist-tag-library-status")).to_contain_text(
        "still referenced by scripts: demo"
    )
    assert len(page.request.get(f"{url}/api/assist-tags").json()["tags"]) == 1
    page.locator("#bind-assist-tag").click()
    playwright.expect(page.locator("#assist-tag-library-status")).to_have_text("Unbound from script")
    assert page.request.get(f"{url}/api/settings/demo").json()["config"]["assistTags"] == []
    page.locator(".assist-tag-form").evaluate("element => element.scrollTop = 0")
    page.screenshot(path=str(directory / f"tag-maker-{width}.png"))
    assert page.locator(".assist-tag-form").evaluate("e => e.scrollWidth <= e.clientWidth")
    assert canvas.evaluate("e => Array.from(e.getContext('2d').getImageData(250, 120, 100, 40).data).some(v => v > 100)")
    preview = page.request.get(f"{url}/api/assist-tags/{tag['name']}/image").body()
    page.once("dialog", lambda dialog: dialog.accept())
    page.locator("#delete-assist-tag").click()
    playwright.expect(page.locator("#assist-tag-library-status")).to_have_text("Tag deleted")
    assert page.request.get(f"{url}/api/assist-tags").json()["tags"] == []
    page.locator("#assist-tag-file").set_input_files({
        "name": "invalid.png", "mimeType": "image/png", "buffer": preview,
    })
    page.locator("#import-assist-tag").click()
    playwright.expect(page.locator("#assist-tag-library-status")).to_contain_text("Assist tag filename")
    playwright.expect(page.locator("#import-assist-tag")).to_be_enabled()
    page.locator("#assist-tag-file").set_input_files({
        "name": tag["name"], "mimeType": "image/png", "buffer": preview,
    })
    page.locator("#import-assist-tag").click()
    playwright.expect(page.locator("#assist-tag-library-status")).to_have_text("Imported Custom")
    assert page.request.get(f"{url}/api/assist-tags").json()["tags"][0]["threshold"] == 0.805
    assert errors == []
    page.close()


@pytest.mark.parametrize("width,height", [(1440, 1000), (390, 844)])
def test_full_run_sends_assist_filter_and_enables_stuck_restart_limit(tag_console, width, height):
    browser, url, directory = tag_console
    page = browser.new_page(viewport={"width": width, "height": height})
    page.set_default_timeout(10000)
    config = page.request.get(f"{url}/api/settings/demo").json()["config"]
    config.update({"round1_turns": 1, "stuckRestart": True, "gameCrushRestart": False})
    assert page.request.put(f"{url}/api/settings/demo", data={
        "config": config, "overwrite": True,
    }).ok
    page.goto(url)
    playwright.expect(page.locator("#start-full-run")).to_be_enabled()
    playwright.expect(page.locator("#full-run-restart-limit")).to_be_enabled()
    requests = []

    def capture_job(route):
        if route.request.method != "POST":
            route.continue_()
            return
        requests.append(route.request.post_data_json)
        route.fulfill(status=409, json={"error": {"message": "Captured test job"}})

    page.route("**/api/jobs", capture_job)
    for special_filter in ("arts", "olga"):
        page.locator("#full-run-assist-filter").select_option(special_filter)
        with page.expect_response(lambda response: response.request.method == "POST" and response.url.endswith("/api/jobs")):
            page.locator("#start-full-run").click()
        assert requests[-1]["payload"]["assist"] == {"special_filter": special_filter}
    page.locator("#full-run-assist-filter").scroll_into_view_if_needed()
    assert page.locator("#full-run-assist-filter").bounding_box()["width"] >= 220
    page.screenshot(path=str(directory / f"run-filter-{width}.png"))
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    config["assistMode"] = "仅礼装"
    assert page.request.put(f"{url}/api/settings/demo", data={
        "config": config, "overwrite": True,
    }).ok
    page.locator("#refresh-settings").click()
    playwright.expect(page.locator("#full-run-assist-filter")).to_be_disabled()
    with page.expect_response(lambda response: response.request.method == "POST" and response.url.endswith("/api/jobs")):
        page.locator("#start-full-run").click()
    assert requests[-1]["payload"]["assist"] == {"special_filter": "any"}
    page.close()


@pytest.mark.parametrize("width,height", [(1440, 1000), (390, 600)])
def test_script_skill_controls_sync_with_json_and_preserve_other_fields(tag_console, width, height):
    browser, url, directory = tag_console
    page = browser.new_page(viewport={"width": width, "height": height})
    page.set_default_timeout(10000)
    config = page.request.get(f"{url}/api/settings/demo").json()["config"]
    config.update({"skillsLevel": [1, 2, 3, 0, 8, 0, 7, 9], "custom": {"unchanged": True}})
    assert page.request.put(f"{url}/api/settings/demo", data={"config": config, "overwrite": True}).ok
    page.goto(url)
    page.locator("#edit-setting").click()
    skills = page.locator("#preset-assist-skills")
    playwright.expect(skills).to_be_visible()
    fields = page.locator("[data-assist-skill-index]")
    playwright.expect(fields.nth(4)).to_have_value("8")
    fields.nth(4).fill("10")
    fields.nth(4).press("Tab")
    edited = json.loads(page.locator("#preset-json").input_value())
    assert edited["skillsLevel"] == [1, 2, 3, 0, 10, 0, 7, 9]
    assert edited["custom"] == {"unchanged": True}
    edited["skillsLevel"] = [8, 8, 8, 5, 5, 5, 0, 0]
    page.locator("#preset-json").fill(json.dumps(edited))
    playwright.expect(fields.nth(0)).to_have_value("8")
    playwright.expect(fields.nth(7)).to_have_value("0")
    fields.nth(7).fill("2")
    fields.nth(7).press("Tab")
    page.locator("#preset-assist-skills").scroll_into_view_if_needed()
    assert page.locator("#preset-dialog").evaluate("element => element.scrollWidth <= element.clientWidth")
    page.screenshot(path=str(directory / f"skill-editor-{width}.png"))
    with page.expect_response(lambda response: response.request.method == "PUT" and "/api/settings/demo" in response.url):
        page.locator("#save-preset").click()
    playwright.expect(page.locator("#preset-dialog")).not_to_be_visible()
    saved = page.request.get(f"{url}/api/settings/demo").json()["config"]
    assert saved["skillsLevel"] == [8, 8, 8, 5, 5, 5, 0, 2]
    assert saved["custom"] == {"unchanged": True}
    page.close()


def test_skill_controls_handle_invalid_json_and_cntw_limits(tag_console):
    browser, url, _directory = tag_console
    page = browser.new_page()
    page.set_default_timeout(10000)
    page.goto(url)
    page.locator("#edit-setting").click()
    fields = page.locator("[data-assist-skill-index]")
    page.locator("#preset-json").fill("{")
    playwright.expect(fields.first).to_be_disabled()
    page.locator("#save-preset").click()
    playwright.expect(page.locator("#preset-error")).to_contain_text("Invalid JSON")
    page.locator("#preset-json").fill(json.dumps({"server": "CNTW", "skillsLevel": [0, 0, 0, 1, 2, 3, 0, 0]}))
    playwright.expect(fields.nth(5)).to_have_value("3")
    playwright.expect(fields.nth(5)).to_be_enabled()
    playwright.expect(fields.nth(6)).to_be_disabled()
    playwright.expect(fields.nth(7)).to_be_disabled()
    page.locator("#cancel-preset").click()
    page.locator("#new-strategy").click()
    playwright.expect(page.locator("#preset-assist-skills")).not_to_be_visible()
    page.close()


@pytest.mark.parametrize("width,height", [(1440, 1000), (390, 600)])
def test_strategy_rule_controls_sync_selected_entry_and_preserve_json(tag_console, width, height):
    browser, url, directory = tag_console
    page = browser.new_page(viewport={"width": width, "height": height})
    page.set_default_timeout(10000)
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    rule = {
        "card1": {"type": 0, "cards": [1], "criticalStar": 0, "more_or_less": True},
        "card2": {"type": 2, "cards": [], "criticalStar": 0, "more_or_less": True},
        "card3": {"type": 2, "cards": [], "criticalStar": 0, "more_or_less": True},
        "breakpoint": [False, True], "colorFirst": True, "custom": {"keep": "first"},
    }
    entries = [{"tag": "First", "strategy": rule}, {
        "tag": "Second", "strategy": {**rule, "breakpoint": [True, False], "custom": {"keep": "second"}},
    }]
    assert page.request.put(f"{url}/api/strategies/rules", data={"entries": entries}).ok
    page.goto(url)
    page.locator("#strategy-select").select_option("rules")
    page.locator("#edit-strategy").click()
    controls = page.locator("#preset-strategy-rules")
    playwright.expect(controls).to_be_visible()
    original_json = page.locator("#preset-json").input_value()
    entry = page.locator("#preset-strategy-entry")
    first = page.locator('[data-strategy-breakpoint="0"]')
    second = page.locator('[data-strategy-breakpoint="1"]')
    color_first = page.locator("#preset-strategy-color-first")
    playwright.expect(first).not_to_be_checked()
    playwright.expect(second).to_be_checked()
    entry.select_option("1")
    assert page.locator("#preset-json").input_value() == original_json
    playwright.expect(first).to_be_checked()
    playwright.expect(second).not_to_be_checked()
    second.check()
    color_first.uncheck()
    updated = json.loads(page.locator("#preset-json").input_value())
    assert updated[0] == entries[0]
    assert updated[1]["strategy"] == {**entries[1]["strategy"], "breakpoint": [True, True], "colorFirst": False}
    updated[1]["strategy"]["breakpoint"] = [False, True]
    page.locator("#preset-json").fill(json.dumps(updated))
    playwright.expect(first).not_to_be_checked()
    controls.scroll_into_view_if_needed()
    assert page.locator("#preset-dialog").evaluate("element => element.scrollWidth <= element.clientWidth")
    assert entry.bounding_box()["width"] >= 220
    page.screenshot(path=str(directory / f"strategy-rules-{width}.png"))
    page.locator("#save-preset").click()
    playwright.expect(page.locator("#preset-dialog")).not_to_be_visible()
    assert page.request.get(f"{url}/api/strategies/rules").json()["entries"] == updated
    page.locator("#edit-setting").click()
    playwright.expect(controls).not_to_be_visible()
    assert errors == []
    page.close()


def test_strategy_rule_controls_disable_for_invalid_or_empty_json(tag_console):
    browser, url, _directory = tag_console
    page = browser.new_page()
    page.set_default_timeout(10000)
    page.goto(url)
    page.locator("#new-strategy").click()
    controls = page.locator("#preset-strategy-rules")
    playwright.expect(controls).to_be_visible()
    playwright.expect(page.locator("#preset-strategy-entry")).to_be_disabled()
    playwright.expect(page.locator("#preset-strategy-color-first")).to_be_disabled()
    page.locator("#preset-json").fill("{")
    playwright.expect(page.locator("#preset-strategy-entry")).to_be_disabled()
    playwright.expect(page.locator('[data-strategy-breakpoint="0"]')).to_be_disabled()
    page.locator("#preset-json").fill(json.dumps([{"tag": "Broken", "strategy": None}]))
    playwright.expect(page.locator("#preset-strategy-entry")).to_be_enabled()
    playwright.expect(page.locator('[data-strategy-breakpoint="0"]')).to_be_disabled()
    playwright.expect(page.locator("#preset-strategy-color-first")).to_be_disabled()
    page.close()


@pytest.mark.parametrize(("width", "height"), [(1440, 1000), (390, 600)])
def test_strategy_card_controls_round_trip_and_reject_invalid_input(tag_console, width, height):
    browser, url, directory = tag_console
    page = browser.new_page(viewport={"width": width, "height": height})
    page.set_default_timeout(10000)
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    rule = {
        "card1": {"type": 0, "cards": [1], "criticalStar": 0, "more_or_less": True},
        "card2": {"type": 1, "cards": ["1B"], "criticalStar": 0, "more_or_less": True, "keep": 123},
        "card3": {"type": 2, "cards": [], "criticalStar": 0, "more_or_less": True},
        "breakpoint": [False, False], "colorFirst": True,
    }
    entries = [{"tag": "Cards", "strategy": rule}, {"tag": "Untouched", "strategy": rule}]
    assert page.request.put(f"{url}/api/strategies/cards", data={"entries": entries}).ok
    page.goto(url)
    page.locator("#strategy-select").select_option("cards")
    page.locator("#edit-strategy").click()
    playwright.expect(page.locator("#preset-dialog")).to_be_visible()
    original_json = page.locator("#preset-json").input_value()
    first = page.locator('[data-strategy-card="card1"]')
    second = page.locator('[data-strategy-card="card2"]')
    third = page.locator('[data-strategy-card="card3"]')
    playwright.expect(first.locator('[data-card-field="type"]')).to_have_value("0")
    playwright.expect(third.locator('[data-card-field="cards"]')).to_be_disabled()
    assert page.locator("#preset-json").input_value() == original_json
    first.locator('[data-card-field="cards"]').fill("3, 2")
    first.locator('[data-card-field="cards"]').press("Tab")
    second.locator('[data-card-field="cards"]').fill("3QS12, S0, 1A")
    second.locator('[data-card-field="cards"]').press("Tab")
    second.locator('[data-card-field="criticalStar"]').fill("4.5")
    second.locator('[data-card-field="criticalStar"]').press("Tab")
    second.locator('[data-card-field="more_or_less"]').select_option("false")
    valid_json = page.locator("#preset-json").input_value()
    second.locator('[data-card-field="cards"]').fill("4X")
    second.locator('[data-card-field="cards"]').press("Tab")
    assert page.locator("#preset-json").input_value() == valid_json
    assert second.locator('[data-card-field="cards"]').evaluate("element => !element.checkValidity()")
    second.locator('[data-card-field="cards"]').fill("3QS12, S0, 1A")
    second.locator('[data-card-field="cards"]').press("Tab")
    updated = json.loads(page.locator("#preset-json").input_value())
    assert updated[1] == entries[1]
    assert updated[0]["strategy"]["card1"]["cards"] == [3, 2]
    assert updated[0]["strategy"]["card2"] == {
        "type": 1, "cards": ["3QS12", "S0", "1A"], "criticalStar": 4.5, "more_or_less": False, "keep": 123,
    }
    third.locator('[data-card-field="type"]').select_option("0")
    playwright.expect(third.locator('[data-card-field="cards"]')).to_have_value("1")
    third.locator('[data-card-field="type"]').select_option("1")
    assert json.loads(page.locator("#preset-json").input_value())[0]["strategy"]["card3"]["cards"]
    third.scroll_into_view_if_needed()
    assert page.locator("#preset-dialog").evaluate("element => element.scrollWidth <= element.clientWidth")
    page.screenshot(path=str(directory / f"strategy-cards-{width}.png"))
    final_entries = json.loads(page.locator("#preset-json").input_value())
    page.locator("#save-preset").click()
    playwright.expect(page.locator("#preset-dialog")).not_to_be_visible()
    assert page.request.get(f"{url}/api/strategies/cards").json()["entries"] == final_entries
    page.locator("#edit-setting").click()
    playwright.expect(first).not_to_be_visible()
    assert errors == []
    page.close()


@pytest.mark.parametrize(("field", "invalid"), [("cards", "4X"), ("criticalStar", "11")])
def test_strategy_invalid_drafts_survive_other_edits_and_block_save(tag_console, field, invalid):
    browser, url, _directory = tag_console
    page = browser.new_page()
    page.set_default_timeout(10000)
    spec = {"type": 1, "cards": ["1B"], "criticalStar": 0, "more_or_less": True}
    strategy = {**{f"card{i}": spec for i in (1, 2, 3)}, "breakpoint": [False, False], "colorFirst": True}
    entries = [{"tag": name, "strategy": strategy} for name in ("First", "Second")]
    assert page.request.put(f"{url}/api/strategies/drafts", data={"entries": entries}).ok
    page.goto(url)
    page.locator("#strategy-select").select_option("drafts")
    page.locator("#edit-strategy").click()
    playwright.expect(page.locator("#preset-dialog")).to_be_visible()
    input_field = page.locator(f'[data-strategy-card="card2"] [data-card-field="{field}"]')
    input_field.fill(invalid)
    input_field.press("Tab")
    page.locator("#preset-strategy-color-first").uncheck()
    playwright.expect(input_field).to_have_value(invalid)
    assert input_field.evaluate("element => !element.checkValidity()")
    page.locator("#save-preset").click()
    playwright.expect(page.locator("#preset-dialog")).to_be_visible()
    page.locator("#preset-strategy-entry").select_option("1")
    page.locator("#save-preset").click()
    playwright.expect(page.locator("#preset-dialog")).to_be_visible()
    playwright.expect(page.locator("#preset-strategy-entry")).to_have_value("0")
    playwright.expect(input_field).to_have_value(invalid)
    assert page.request.get(f"{url}/api/strategies/drafts").json()["entries"] == entries
    page.locator("#preset-json").fill(json.dumps(entries))
    assert input_field.evaluate("element => element.checkValidity()")
    page.close()


def test_strategy_card_renderer_tolerates_nonprimitive_preference_elements(tag_console):
    browser, url, _directory = tag_console
    page = browser.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(url)
    page.locator("#new-strategy").click()
    playwright.expect(page.locator("#preset-dialog")).to_be_visible()
    spec = {"type": 2, "cards": [{"toString": None}], "criticalStar": 0, "more_or_less": True}
    entries = [{"tag": "Malformed", "strategy": {
        **{f"card{i}": spec for i in (1, 2, 3)}, "breakpoint": [False, False], "colorFirst": True,
    }}]
    source = json.dumps(entries)
    page.locator("#preset-json").fill(source)
    playwright.expect(page.locator('[data-strategy-card="card3"] [data-card-field="type"]')).to_have_value("2")
    assert page.locator("#preset-json").input_value() == source
    assert errors == []
    page.close()


@pytest.mark.parametrize("failure", ["image", "request"])
def test_tag_capture_failure_clears_old_image_and_can_be_retried(tag_console, failure):
    browser, url, _directory = tag_console
    page = browser.new_page()
    page.set_default_timeout(10000)
    page.goto(url)
    page.locator("#open-assist-tags").click()
    page.locator("#capture-assist-tag-screen").click()
    playwright.expect(page.locator("#assist-tag-maker-status")).to_have_text("1 supports matched")
    payload = page.request.post(f"{url}/api/assist-tags/candidates", data={"setting_name": "demo"}).json()

    def fail_capture(route):
        if failure == "request":
            route.fulfill(status=500, json={"error": {"message": "Capture failed"}})
        else:
            route.fulfill(status=200, json={**payload, "screenshot_base64": "bm90IGFuIGltYWdl"})

    page.route("**/api/assist-tags/candidates", fail_capture)
    page.locator("#capture-assist-tag-screen").click()
    playwright.expect(page.locator("#assist-tag-maker-status")).to_contain_text(
        "Capture failed" if failure == "request" else "could not be displayed"
    )
    playwright.expect(page.locator("#assist-tag-canvas-empty")).to_be_visible()
    playwright.expect(page.locator("#assist-tag-candidate")).to_be_disabled()
    playwright.expect(page.locator("#save-assist-tag")).to_be_disabled()
    assert page.locator("#assist-tag-canvas").evaluate(
        "e => Array.from(e.getContext('2d').getImageData(0, 0, e.width, e.height).data).every(value => value === 0)"
    )
    page.unroute("**/api/assist-tags/candidates", fail_capture)
    page.locator("#capture-assist-tag-screen").click()
    playwright.expect(page.locator("#assist-tag-maker-status")).to_have_text("1 supports matched")
    playwright.expect(page.locator("#assist-tag-canvas-empty")).to_be_hidden()
    playwright.expect(page.locator("#assist-tag-candidate")).to_be_enabled()
    page.close()
