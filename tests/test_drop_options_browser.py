import json
import os

import pytest
from PIL import Image, ImageDraw

playwright = pytest.importorskip("playwright.sync_api")
from tests.test_assist_tags_browser import tag_console
from tests.test_strategy_assignment_browser import _config, _seed

pytestmark = pytest.mark.skipif(not os.environ.get("BBCHANNEL_TEST_CHROMIUM"), reason="Set BBCHANNEL_TEST_CHROMIUM.")


def _assets(directory):
    for index, path in enumerate(("a/item.png", "b/item.png", "only.jpg")):
        target = directory / "assets" / "drop" / path
        target.parent.mkdir(parents=True, exist_ok=True)
        image = Image.new("RGB", (88, 96), (50, 90 + index * 50, 145))
        ImageDraw.Draw(image).rectangle((10, 12, 75, 82), outline="yellow", width=5)
        image.save(target)


def _open(page, url):
    page.goto(url)
    page.locator("#edit-setting").click()
    playwright.expect(page.locator("#preset-drop-options")).to_be_attached(timeout=1000)
    page.locator("#preset-drop-options summary").click()


@pytest.mark.parametrize("width,height,locale", [(1440, 1000, "en-US"), (390, 844, "zh-CN")])
def test_drop_controls_keep_legacy_path_then_save_explicit_selection(tag_console, width, height, locale):
    browser, url, directory = tag_console
    _assets(directory)
    page = browser.new_page(viewport={"width": width, "height": height}, locale=locale)
    _entries, original = _seed(page, url)
    original.update({"dropStopNum": 2, "dropImage": r"E:\old\assets\drop\b\item.png"})
    assert page.request.put(f"{url}/api/settings/demo", data={"config": original, "overwrite": True}).ok
    _open(page, url)
    number = page.locator('[data-run-option="dropStopNum"]')
    picker = page.locator("#preset-drop-image")
    playwright.expect(number).to_have_value("2")
    playwright.expect(picker).to_have_value("drop/b/item.png")
    assert _config(page) == original
    playwright.expect(page.locator("#preset-drop-preview img")).to_be_visible()
    playwright.expect(page.locator("#preset-drop-preview img")).to_have_js_property("naturalWidth", 88)
    number.fill("3")
    assert _config(page)["dropStopNum"] == 3
    picker.select_option("drop/a/item.png")
    assert _config(page) == {**original, "dropStopNum": 3, "dropImage": "drop/a/item.png"}
    if locale == "zh-CN":
        playwright.expect(page.locator("#preset-drop-options summary")).to_have_text("掉落停止")
    page.locator("#preset-drop-options").scroll_into_view_if_needed()
    page.screenshot(path=str(directory / f"drop-options-{width}.png"))
    assert page.locator(".preset-form").evaluate("e => e.scrollWidth <= e.clientWidth")
    assert page.request.get(f"{url}/api/settings/demo").json()["config"] == original
    page.locator("#save-preset").click()
    playwright.expect(page.locator("#preset-dialog")).not_to_be_visible()
    run = page.request.get(f"{url}/api/settings/demo/plan").json()["run"]
    assert run["drop_stop_num"] == 3
    assert run["drop_image"] == "drop/a/item.png"
    page.close()


@pytest.mark.parametrize("legacy", [None, {}, "2", -1, 1.5, 9007199254740992])
def test_legacy_drop_fields_are_preserved_until_explicitly_edited(tag_console, legacy):
    browser, url, directory = tag_console
    _assets(directory)
    page = browser.new_page()
    _entries, original = _seed(page, url)
    original.update({"dropStopNum": legacy, "dropImage": legacy})
    assert page.request.put(f"{url}/api/settings/demo", data={"config": original, "overwrite": True}).ok
    _open(page, url)
    playwright.expect(page.locator('[data-run-option="dropStopNum"]')).to_have_value("")
    assert _config(page) == original
    page.locator("#save-preset").click()
    playwright.expect(page.locator("#preset-dialog")).not_to_be_visible()
    assert page.request.get(f"{url}/api/settings/demo").json()["config"] == original
    _open(page, url)
    page.locator("#preset-drop-image").select_option("")
    assert "dropImage" not in _config(page)
    assert _config(page)["dropStopNum"] == legacy
    page.close()


@pytest.mark.parametrize("invalid", ["", "-1", "2.5", "9007199254740992"])
def test_invalid_drop_count_survives_renders_and_blocks_save(tag_console, invalid):
    browser, url, directory = tag_console
    _assets(directory)
    page = browser.new_page()
    _entries, original = _seed(page, url)
    _open(page, url)
    number = page.locator('[data-run-option="dropStopNum"]')
    number.fill(invalid)
    number.press("Tab")
    page.locator("#preset-drop-image").select_option("drop/only.jpg")
    playwright.expect(number).to_have_value(invalid)
    assert "dropStopNum" not in _config(page)
    page.locator("#preset-drop-options summary").click()
    page.locator("#save-preset").click()
    playwright.expect(page.locator("#preset-dialog")).to_be_visible()
    assert page.locator("#preset-drop-options").evaluate("e => e.open")
    assert page.request.get(f"{url}/api/settings/demo").json()["config"] == original
    page.locator("#preset-json").fill(json.dumps(original))
    page.locator("#save-preset").click()
    playwright.expect(page.locator("#preset-dialog")).not_to_be_visible()
    page.close()


def test_drop_defaults_and_partial_draft_survive_late_catalog(tag_console):
    browser, url, directory = tag_console
    _assets(directory)
    page = browser.new_page()
    _entries, original = _seed(page, url)
    pending = []
    response = page.request.get(f"{url}/api/drop-templates")
    page.route("**/api/drop-templates*", lambda route: pending.append(route))
    _open(page, url)
    number = page.locator('[data-run-option="dropStopNum"]')
    playwright.expect(number).to_have_value("0")
    assert _config(page) == original
    number.fill("")
    number.press_sequentially("1e")
    pending.pop().fulfill(response=response)
    playwright.expect(page.locator("#preset-drop-image option[value='drop/only.jpg']")).to_be_attached()
    assert number.evaluate("e => e.validity.badInput")
    playwright.expect(number).to_be_focused()
    number.press("End")
    number.press_sequentially("1")
    assert _config(page)["dropStopNum"] == 10
    number.press("Enter")
    playwright.expect(page.locator("#preset-dialog")).not_to_be_visible()
    page.close()


def test_drop_catalog_failure_allows_clear_save_and_retry(tag_console):
    browser, url, directory = tag_console
    _assets(directory)
    page = browser.new_page()
    _entries, original = _seed(page, url)
    original["dropImage"] = "missing.png"
    assert page.request.put(f"{url}/api/settings/demo", data={"config": original, "overwrite": True}).ok
    page.route("**/api/drop-templates*", lambda route: route.fulfill(status=500, json={"error": {"message": "Catalog failed"}}))
    _open(page, url)
    playwright.expect(page.locator("#preset-drop-status")).to_contain_text("Catalog failed")
    assert _config(page) == original
    page.locator("#preset-drop-image").select_option("")
    assert "dropImage" not in _config(page)
    page.unroute("**/api/drop-templates*")
    page.locator("#refresh-drop-templates").click()
    playwright.expect(page.locator("#preset-drop-image option[value='drop/only.jpg']")).to_be_attached()
    page.locator("#save-preset").click()
    playwright.expect(page.locator("#preset-dialog")).not_to_be_visible()
    page.close()


def test_drop_controls_lock_and_stale_catalog_does_not_override_new_editor(tag_console):
    browser, url, directory = tag_console
    _assets(directory)
    page = browser.new_page()
    _seed(page, url)
    _open(page, url)
    pending = []
    response = page.request.get(f"{url}/api/strategies/Preset")
    page.route("**/api/strategies/Preset", lambda route: pending.append(route))
    page.locator("#apply-turn-strategy").click()
    for selector in ("#preset-drop-image", "[data-run-option='dropStopNum']", "#refresh-drop-templates"):
        playwright.expect(page.locator(selector)).to_be_disabled()
    pending.pop().fulfill(response=response)
    playwright.expect(page.locator("#preset-drop-image")).to_be_enabled()
    response = page.request.get(f"{url}/api/drop-templates")
    page.route("**/api/drop-templates*", lambda route: pending.append(route))
    page.locator("#refresh-drop-templates").click()
    page.locator("#cancel-preset").click()
    page.locator("#new-strategy").click()
    pending.pop().fulfill(response=response)
    playwright.expect(page.locator("#preset-drop-options")).to_be_hidden()
    page.close()


def test_drop_catalog_for_replaced_raw_path_cannot_overwrite_newer_choice(tag_console):
    browser, url, directory = tag_console
    _assets(directory)
    page = browser.new_page()
    _entries, original = _seed(page, url)
    old = page.request.get(f"{url}/api/drop-templates", params={"configured": "drop/b/item.png"})
    new = page.request.get(f"{url}/api/drop-templates", params={"configured": "drop/a/item.png"})
    original["dropImage"] = "drop/b/item.png"
    assert page.request.put(f"{url}/api/settings/demo", data={"config": original, "overwrite": True}).ok
    pending = []
    page.route("**/api/drop-templates?configured=*", lambda route: pending.append(route))
    _open(page, url)
    updated = {**original, "dropImage": "drop/a/item.png"}
    page.locator("#preset-json").fill(json.dumps(updated))
    number = page.locator('[data-run-option="dropStopNum"]')
    number.fill("3")
    pending.pop().fulfill(response=new)
    playwright.expect(page.locator("#preset-drop-image")).to_have_value("drop/a/item.png")
    pending.pop().fulfill(response=old)
    playwright.expect(page.locator("#preset-drop-image")).to_have_value("drop/a/item.png")
    playwright.expect(number).to_be_focused()
    assert _config(page) == {**updated, "dropStopNum": 3}
    page.close()


def test_missing_preview_does_not_block_save_and_refresh_retries_image(tag_console):
    browser, url, directory = tag_console
    _assets(directory)
    page = browser.new_page()
    _entries, original = _seed(page, url)
    original.update({"dropStopNum": 2, "dropImage": "drop/only.jpg"})
    assert page.request.put(f"{url}/api/settings/demo", data={"config": original, "overwrite": True}).ok
    page.route("**/api/drop-templates/image?*", lambda route: route.fulfill(status=404))
    _open(page, url)
    playwright.expect(page.locator("#preset-drop-preview-status")).to_have_text("Preview unavailable")
    assert _config(page) == original
    page.unroute("**/api/drop-templates/image?*")
    page.locator("#refresh-drop-templates").click()
    playwright.expect(page.locator("#preset-drop-preview img")).to_have_js_property("naturalWidth", 88)
    page.locator("#save-preset").click()
    playwright.expect(page.locator("#preset-dialog")).not_to_be_visible()
    assert page.request.get(f"{url}/api/settings/demo").json()["config"] == original
    page.close()


def test_drop_controls_lock_while_saving_and_during_invalid_json(tag_console):
    browser, url, directory = tag_console
    _assets(directory)
    page = browser.new_page()
    _entries, original = _seed(page, url)
    _open(page, url)
    for raw in ("{", "[]", "null"):
        page.locator("#preset-json").fill(raw)
        playwright.expect(page.locator("#preset-drop-image")).to_be_disabled()
        playwright.expect(page.locator('[data-run-option="dropStopNum"]')).to_be_disabled()
    page.locator("#preset-json").fill(json.dumps(original))
    playwright.expect(page.locator("#preset-drop-image")).to_be_enabled()
    pending = []
    page.route("**/api/settings/demo", lambda route: pending.append(route))
    page.locator("#save-preset").click()
    for selector in ("#preset-drop-image", "[data-run-option='dropStopNum']", "#refresh-drop-templates"):
        playwright.expect(page.locator(selector)).to_be_disabled()
    pending.pop().fulfill(status=500, json={"error": {"message": "Save failed"}})
    playwright.expect(page.locator("#preset-drop-image")).to_be_enabled()
    page.close()


@pytest.mark.parametrize("path", ["item.png", "drop/missing/item.png"])
def test_ambiguous_or_missing_drop_selection_stays_visible_until_cleared(tag_console, path):
    browser, url, directory = tag_console
    _assets(directory)
    page = browser.new_page()
    _entries, original = _seed(page, url)
    original.update({"dropStopNum": 2, "dropImage": path})
    assert page.request.put(f"{url}/api/settings/demo", data={"config": original, "overwrite": True}).ok
    _open(page, url)
    playwright.expect(page.locator("#preset-drop-status")).to_have_text("Drop image unavailable or ambiguous.")
    playwright.expect(page.locator("#preset-drop-image")).to_have_value("__current__")
    assert _config(page) == original
    page.locator("#preset-drop-image").select_option("")
    assert _config(page) == {key: value for key, value in original.items() if key != "dropImage"}
    page.close()
