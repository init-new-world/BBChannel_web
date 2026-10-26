import json
import os
import re

import pytest
from PIL import Image

playwright = pytest.importorskip("playwright.sync_api")
from tests.test_assist_tags_browser import tag_console
from tests.test_master_editor_browser import _masters
from tests.test_strategy_assignment_browser import _config, _seed

pytestmark = pytest.mark.skipif(not os.environ.get("BBCHANNEL_TEST_CHROMIUM"), reason="Set BBCHANNEL_TEST_CHROMIUM.")


def _portraits(directory):
    _masters(directory)
    portraits = directory / "assets" / "masterface"
    portraits.mkdir()
    for name in ("Default outfit", "Combat outfit", "Travel outfit with a long descriptive catalog name"):
        for sex, color in ((0, "red"), (1, "blue")):
            Image.new("RGBA", (64, 64), color).save(portraits / f"{name}_{sex}.png")


def _seed_outfit(page, url):
    _entries, original = _seed(page, url)
    original["master_equip"] = 7
    assert page.request.put(f"{url}/api/settings/demo", data={"config": original, "overwrite": True}).ok
    return original


def _open(page, url):
    page.goto(url)
    page.locator("#edit-setting").click()
    page.locator("#preset-team summary").click()
    playwright.expect(page.locator("#preset-master-preview")).to_be_attached(timeout=1000)


def _loaded(page, sex, equip="7"):
    image = page.locator("#preset-master-portrait img")
    playwright.expect(image).to_be_visible()
    playwright.expect(image).to_have_attribute("src", re.compile(f"sex={sex}(?:&|$)"))
    playwright.expect(image).to_have_attribute("src", re.compile(rf"(?:\?|&)equip={re.escape(equip)}(?:&|$)"))
    playwright.expect(image).to_have_js_property("naturalWidth", 64)
    pixel = image.evaluate("e => { const c=document.createElement('canvas'); c.width=c.height=1; const x=c.getContext('2d'); x.drawImage(e,0,0,1,1); return Array.from(x.getImageData(0,0,1,1).data); }")
    assert pixel == ([255, 0, 0, 255] if sex == 0 else [0, 0, 255, 255])


@pytest.mark.parametrize("width,height,locale", [(1440, 1000, "en-US"), (390, 844, "zh-CN")])
def test_master_portrait_tracks_outfit_gender_and_clear_without_changing_draft(tag_console, width, height, locale):
    browser, url, directory = tag_console
    _portraits(directory)
    page = browser.new_page(viewport={"width": width, "height": height}, locale=locale)
    original = _seed_outfit(page, url)
    _open(page, url)
    _loaded(page, 0)
    assert _config(page) == original
    page.locator("#preset-master-sex").select_option("1")
    _loaded(page, 1)
    page.locator("#preset-master-equip").select_option("008")
    _loaded(page, 1, "008")
    assert _config(page) == {**original, "master_sex": 1, "master_equip": "008"}
    page.locator("#preset-master-preview").scroll_into_view_if_needed()
    page.screenshot(path=str(directory / f"master-portrait-{width}.png"))
    assert page.locator(".preset-form").evaluate("e => e.scrollWidth <= e.clientWidth")
    page.locator("#preset-master-equip").select_option("")
    playwright.expect(page.locator("#preset-master-preview")).to_be_hidden()
    assert "master_equip" not in _config(page)
    assert _config(page)["master_sex"] == 1
    assert page.request.get(f"{url}/api/settings/demo").json()["config"] == original
    page.close()


def test_master_portrait_failure_does_not_block_save_and_can_retry(tag_console):
    browser, url, directory = tag_console
    _portraits(directory)
    page = browser.new_page()
    original = _seed_outfit(page, url)
    page.route("**/api/masters/image?*", lambda route: route.fulfill(status=503))
    _open(page, url)
    status = page.locator("#preset-master-portrait-status")
    playwright.expect(status).to_have_text("Preview unavailable")
    playwright.expect(page.locator("#save-preset")).to_be_enabled()
    assert _config(page) == original
    page.locator("#save-preset").click()
    playwright.expect(page.locator("#preset-dialog")).not_to_be_visible()
    _open(page, url)
    playwright.expect(status).to_have_text("Preview unavailable")
    page.unroute("**/api/masters/image?*")
    page.locator("#retry-master-portrait").click()
    _loaded(page, 0)
    playwright.expect(status).to_be_empty()
    playwright.expect(page.locator("#retry-master-portrait")).to_be_hidden()
    assert _config(page) == original
    page.close()


def test_late_portrait_failure_cannot_replace_a_new_gender_or_reopened_editor(tag_console):
    browser, url, directory = tag_console
    _portraits(directory)
    page = browser.new_page()
    original = _seed_outfit(page, url)
    male = page.request.get(f"{url}/api/masters/image", params={"equip": "7", "sex": "1"})
    female = page.request.get(f"{url}/api/masters/image", params={"equip": "7", "sex": "0"})
    assert male.ok and female.ok
    pending = []
    page.route("**/api/masters/image?*", lambda route: pending.append(route))
    _open(page, url)
    playwright.expect(page.locator("#preset-master-portrait img")).to_have_attribute("src", re.compile("sex=0"))
    page.locator("#preset-master-sex").select_option("1")
    playwright.expect(page.locator("#preset-master-portrait img")).to_have_attribute("src", re.compile("sex=1"))
    pending.pop().fulfill(response=male)
    _loaded(page, 1)
    pending.pop().fulfill(status=404)
    playwright.expect(page.locator("#preset-master-portrait-status")).to_be_empty()
    page.locator("#preset-master-sex").select_option("0")
    playwright.expect(page.locator("#preset-master-portrait img")).to_have_attribute("src", re.compile("sex=0"))
    page.locator("#cancel-preset").click()
    _open(page, url)
    playwright.expect(page.locator("#preset-master-portrait img")).to_have_attribute("src", re.compile("sex=0"))
    pending.pop().fulfill(response=female)
    _loaded(page, 0)
    pending.pop().fulfill(status=404)
    playwright.expect(page.locator("#preset-master-portrait-status")).to_be_empty()
    assert _config(page) == original
    page.close()


@pytest.mark.parametrize("sex", [None, "1", False, {}])
def test_legacy_gender_is_not_silently_used_for_portrait_until_replaced(tag_console, sex):
    browser, url, directory = tag_console
    _portraits(directory)
    page = browser.new_page()
    original = _seed_outfit(page, url)
    original["master_sex"] = sex
    assert page.request.put(f"{url}/api/settings/demo", data={"config": original, "overwrite": True}).ok
    _open(page, url)
    playwright.expect(page.locator("#preset-master-equip")).to_be_enabled()
    playwright.expect(page.locator("#preset-master-preview")).to_be_hidden()
    assert _config(page) == original
    page.locator("#preset-master-sex").select_option("0")
    _loaded(page, 0)
    assert _config(page) == {**original, "master_sex": 0}
    page.close()


def test_master_portrait_retry_locks_with_apply_save_and_invalid_json(tag_console):
    browser, url, directory = tag_console
    _portraits(directory)
    page = browser.new_page()
    original = _seed_outfit(page, url)
    page.route("**/api/masters/image?*", lambda route: route.fulfill(status=404))
    _open(page, url)
    retry = page.locator("#retry-master-portrait")
    playwright.expect(retry).to_be_visible()
    pending = []
    response = page.request.get(f"{url}/api/strategies/Preset")
    page.route("**/api/strategies/Preset", lambda route: pending.append(route))
    page.locator("#apply-turn-strategy").click()
    playwright.expect(retry).to_be_disabled()
    pending.pop().fulfill(response=response)
    playwright.expect(retry).to_be_enabled()
    page.locator("#preset-json").fill("{")
    playwright.expect(page.locator("#preset-master-preview")).to_be_hidden()
    page.locator("#preset-json").fill(json.dumps(original))
    playwright.expect(retry).to_be_enabled()
    page.route("**/api/settings/demo", lambda route: pending.append(route))
    page.locator("#save-preset").click()
    playwright.expect(retry).to_be_disabled()
    pending.pop().fulfill(status=500, json={"error": {"message": "Save failed"}})
    playwright.expect(retry).to_be_enabled()
    page.close()
