import base64
from io import BytesIO
import os

import pytest
from PIL import Image

playwright = pytest.importorskip("playwright.sync_api")
from tests.test_assist_tags_browser import tag_console
pytestmark = pytest.mark.skipif(
    not os.environ.get("BBCHANNEL_TEST_CHROMIUM"),
    reason="Set BBCHANNEL_TEST_CHROMIUM to a local Chromium executable.",
)


def drag_crop(page, start, end):
    canvas = page.locator("#assist-tag-canvas")
    canvas.scroll_into_view_if_needed()
    box = canvas.bounding_box()
    page.mouse.move(box["x"] + box["width"] * start[0] / 1280,
                    box["y"] + box["height"] * start[1] / 720)
    page.mouse.down()
    page.mouse.move(box["x"] + box["width"] * end[0] / 1280,
                    box["y"] + box["height"] * end[1] / 720, steps=5)
    page.mouse.up()


def expect_empty_capture(page):
    playwright.expect(page.locator("#assist-tag-canvas-empty")).to_be_visible()
    playwright.expect(page.locator("#assist-tag-candidate option")).to_have_count(0)
    playwright.expect(page.locator("#assist-tag-crop-status")).to_have_text("Not selected")
    playwright.expect(page.locator("#save-assist-tag")).to_be_disabled()
    assert page.locator("#assist-tag-canvas").evaluate(
        "e => !e.getContext('2d').getImageData(250, 120, 1, 1).data.some(v => v)"
    )


@pytest.mark.parametrize("width,height", [(1440, 1000), (390, 844)])
def test_command_tag_capture_crop_bind_import_and_modes(tag_console, width, height):
    browser, url, directory = tag_console
    page = browser.new_page(viewport={"width": width, "height": height})
    page.set_default_timeout(10000)
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(url)
    page.locator("#open-assist-tags").click()
    command_mode = page.get_by_role("tab", name="Command Cards", exact=True)
    playwright.expect(command_mode).to_be_visible()
    command_mode.click()
    playwright.expect(command_mode).to_have_attribute("aria-selected", "true")
    with page.expect_response("**/api/command-tags/candidates") as capture:
        page.locator("#capture-assist-tag-screen").click()
    payload = capture.value.json()
    playwright.expect(page.locator("#assist-tag-maker-status")).to_have_text("5 command cards")
    assert "setting_name" not in capture.value.request.post_data_json
    assert payload["candidate_count"] == 5
    page.locator("#assist-tag-candidate").select_option("2")
    candidate = payload["candidates"][2]
    left, top, crop_width, crop_height = candidate["bounds"]
    right, bottom = left + crop_width, top + crop_height
    drag_crop(page, (left - 10, top - 10), (min(right + 10, 1280), min(bottom + 10, 720)))
    playwright.expect(page.locator("#assist-tag-crop-status")).to_have_text(
        f"{left},{top} -> {right},{bottom}"
    )
    page.locator("#assist-tag-label").fill("CommandDemo")
    page.locator("#assist-tag-threshold").fill("0.805")
    with page.expect_request(lambda request: request.method == "POST" and request.url.endswith("/api/command-tags")) as saved:
        page.locator("#save-assist-tag").click()
    playwright.expect(page.locator("#assist-tag-maker-status")).to_have_text("Saved CommandDemo")
    request = saved.value.post_data_json
    assert request["slot"] == candidate["slot"]
    assert request["bounds"] == [left, top, right, bottom]
    assert request["screenshot_base64"] == payload["screenshot_base64"]
    assert "anchor" not in request
    tag = page.request.get(f"{url}/api/command-tags").json()["tags"][0]
    assert tag["image_size"] == [crop_width, crop_height]
    assert tag["source_size"] == [1280, 720]
    assert tag["threshold"] == 0.805
    page.locator("#bind-assist-tag").click()
    playwright.expect(page.locator("#assist-tag-library-status")).to_have_text("Bound to script as S0")
    playwright.expect(page.locator("#assist-tag-binding-status")).to_have_text("Bound as S0")
    assert page.request.get(f"{url}/api/settings/demo").json()["config"]["specialKeys"] == [tag["template_path"]]
    page.once("dialog", lambda dialog: dialog.accept())
    page.locator("#delete-assist-tag").click()
    playwright.expect(page.locator("#assist-tag-library-status")).to_contain_text("demo")
    assert len(page.request.get(f"{url}/api/command-tags").json()["tags"]) == 1
    page.locator(".assist-tag-form").evaluate("e => e.scrollTop = 0")
    page.screenshot(path=str(directory / f"command-tags-{width}.png"))
    assert page.locator(".assist-tag-form").evaluate("e => e.scrollWidth <= e.clientWidth")
    assert page.locator("#assist-tag-canvas").evaluate("e => e.width === 1280 && e.height === 720")
    assert page.locator("#assist-tag-canvas").evaluate(
        "e => new Set(e.getContext('2d').getImageData(0, 0, 1280, 720).data).size > 20"
    )
    if width < 900:
        capture_box = page.locator(".assist-tag-capture").bounding_box()
        library_box = page.locator(".assist-tag-library").bounding_box()
        assert library_box["y"] >= capture_box["y"] + capture_box["height"]
        page.locator(".assist-tag-library").scroll_into_view_if_needed()
        page.screenshot(path=str(directory / f"command-tags-library-{width}.png"))
    page.locator("#bind-assist-tag").click()
    playwright.expect(page.locator("#assist-tag-library-status")).to_have_text("Unbound from script")
    assert page.request.get(f"{url}/api/settings/demo").json()["config"]["specialKeys"] == []
    preview = page.request.get(f"{url}/api/command-tags/{tag['name']}/image").body()
    page.once("dialog", lambda dialog: dialog.accept())
    page.locator("#delete-assist-tag").click()
    playwright.expect(page.locator("#assist-tag-library-status")).to_have_text("Tag deleted")
    page.locator("#assist-tag-file").set_input_files({
        "name": tag["name"], "mimeType": "image/png", "buffer": preview,
    })
    page.locator("#import-assist-tag").click()
    playwright.expect(page.locator("#assist-tag-library-status")).to_have_text("Imported CommandDemo")
    page.get_by_role("tab", name="Assist", exact=True).click()
    expect_empty_capture(page)
    playwright.expect(page.locator("#assist-tag-list option")).to_have_count(0)
    page.locator("#capture-assist-tag-screen").click()
    playwright.expect(page.locator("#assist-tag-maker-status")).to_have_text("1 supports matched")
    drag_crop(page, (250, 120), (350, 160))
    playwright.expect(page.locator("#assist-tag-crop-status")).to_have_text("250,120 -> 350,160")
    page.locator("#assist-tag-label").fill("AssistDemo")
    page.locator("#save-assist-tag").click()
    playwright.expect(page.locator("#assist-tag-maker-status")).to_have_text("Saved AssistDemo")
    page.locator("#bind-assist-tag").click()
    playwright.expect(page.locator("#assist-tag-library-status")).to_have_text("Bound to script")
    assert len(page.request.get(f"{url}/api/assist-tags").json()["tags"]) == 1
    command_mode.click()
    expect_empty_capture(page)
    playwright.expect(page.locator("#assist-tag-list option")).to_have_text(["CommandDemo"])
    playwright.expect(page.locator("#assist-tag-file")).to_have_value("")
    assert errors == []
    page.close()


def test_command_capture_without_setting(tag_console):
    browser, url, _directory = tag_console
    page = browser.new_page()
    assert page.request.delete(f"{url}/api/settings/demo").ok
    page.goto(url)
    page.locator("#open-assist-tags").click()
    playwright.expect(page.locator("#capture-assist-tag-screen")).to_be_disabled()
    page.get_by_role("tab", name="Command Cards", exact=True).click()
    playwright.expect(page.locator("#capture-assist-tag-screen")).to_be_enabled()
    page.locator("#capture-assist-tag-screen").click()
    playwright.expect(page.locator("#assist-tag-maker-status")).to_have_text("5 command cards")
    playwright.expect(page.locator("#bind-assist-tag")).to_be_disabled()
    page.close()


def test_command_tag_can_unbind_legacy_array_entry(tag_console):
    browser, url, _directory = tag_console
    page = browser.new_page()
    output = BytesIO()
    Image.new("RGB", (20, 20), "red").save(output, format="PNG")
    name = "[Legacy]W1280H720DXL20DXR40DYT60DYB80CON8.png"
    response = page.request.post(f"{url}/api/command-tags/import", data={
        "name": name, "image_base64": base64.b64encode(output.getvalue()).decode("ascii"),
    })
    assert response.ok
    config = page.request.get(f"{url}/api/settings/demo").json()["config"]
    config["specialKeys"] = [[f"D:\\old\\assets\\battle\\customCommandCard\\{name}", "2B"]]
    assert page.request.put(f"{url}/api/settings/demo", data={"config": config, "overwrite": True}).ok
    page.goto(url)
    page.locator("#open-assist-tags").click()
    page.get_by_role("tab", name="Command Cards", exact=True).click()
    playwright.expect(page.locator("#assist-tag-binding-status")).to_have_text("Bound as S0")
    with page.expect_request("**/api/settings/demo/command-tags") as request:
        page.locator("#bind-assist-tag").click()
    assert request.value.post_data_json["bound"] is False
    playwright.expect(page.locator("#assist-tag-library-status")).to_have_text("Unbound from script")
    assert page.request.get(f"{url}/api/settings/demo").json()["config"]["specialKeys"] == []
    page.close()


def test_stale_command_capture_cannot_repopulate_switched_mode(tag_console):
    browser, url, _directory = tag_console
    page = browser.new_page()
    pending = []
    page.route("**/api/command-tags/candidates", lambda route: pending.append(route))
    page.goto(url)
    page.locator("#open-assist-tags").click()
    page.get_by_role("tab", name="Command Cards", exact=True).click()
    page.locator("#capture-assist-tag-screen").click()
    playwright.expect(page.locator("#assist-tag-maker-status")).to_have_text("Capturing...")
    page.get_by_role("tab", name="Assist", exact=True).click()
    page.get_by_role("tab", name="Command Cards", exact=True).click()
    assert len(pending) == 1
    response = page.request.post(f"{url}/api/command-tags/candidates", data={})
    pending[0].fulfill(response=response)
    page.locator("#assist-tag-label").fill("AfterSwitch")
    expect_empty_capture(page)
    playwright.expect(page.locator("#assist-tag-maker-status")).to_have_text("Idle")
    playwright.expect(page.locator("#capture-assist-tag-screen")).to_be_enabled()
    page.close()
