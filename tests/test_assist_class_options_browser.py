import json
import os

import pytest

playwright = pytest.importorskip("playwright.sync_api")
from tests.test_assist_tags_browser import tag_console
from tests.test_strategy_assignment_browser import _config, _seed

pytestmark = pytest.mark.skipif(
    not os.environ.get("BBCHANNEL_TEST_CHROMIUM"),
    reason="Set BBCHANNEL_TEST_CHROMIUM to a local Chromium executable.",
)


def _toggle(page):
    return page.locator('[data-assist-option="allNotSkip"]')


@pytest.mark.parametrize("width,height,locale,label", [
    (1440, 1000, "en-US", "Keep ALL tab"), (390, 844, "zh-CN", "ALL阶不跳转"),
])
def test_assist_all_tab_default_and_saved_plan(tag_console, width, height, locale, label):
    browser, url, directory = tag_console
    page = browser.new_page(viewport={"width": width, "height": height}, locale=locale)
    _entries, original = _seed(page, url)
    original.pop("allNotSkip", None)
    assert page.request.put(f"{url}/api/settings/demo", data={"config": original, "overwrite": True}).ok
    page.goto(url)
    page.locator("#edit-setting").click()
    page.locator("#preset-assist-options summary").click()
    playwright.expect(_toggle(page)).to_be_checked(timeout=2000)
    playwright.expect(_toggle(page).locator("..")).to_have_text(label)
    assert _config(page) == original
    _toggle(page).uncheck()
    expected = {**original, "allNotSkip": False}
    assert _config(page) == expected
    assert page.request.get(f"{url}/api/settings/demo").json()["config"] == original
    page.locator("#preset-assist-options").scroll_into_view_if_needed()
    page.screenshot(path=str(directory / f"assist-class-options-{width}.png"))
    assert page.locator(".preset-form").evaluate("e => e.scrollWidth <= e.clientWidth")
    page.locator("#save-preset").click()
    playwright.expect(page.locator("#preset-dialog")).not_to_be_visible()
    assert page.request.get(f"{url}/api/settings/demo/plan").json()["assist"]["all_not_skip"] is False
    page.close()


@pytest.mark.parametrize("value", [0, 1, [], {}, [0], {"enabled": False}, None, "false"])
def test_assist_all_tab_legacy_truth_value_is_preserved(tag_console, value):
    browser, url, _directory = tag_console
    page = browser.new_page()
    page.goto(url)
    page.locator("#new-setting").click()
    raw = {"server": "CH", "assistMode": "仅从者", "allNotSkip": value, "custom": [1, 2]}
    page.locator("#preset-json").fill(json.dumps(raw))
    page.locator("#preset-assist-options summary").click()
    assert _toggle(page).is_checked() == bool(value)
    assert _config(page) == raw
    _toggle(page).click()
    assert _config(page) == {**raw, "allNotSkip": not bool(value)}
    page.close()


@pytest.mark.parametrize("mode,enabled", [
    ("从者礼装", True), ("仅从者", True), ("冠位助战", True),
    ("仅礼装", False), ("冠位助战仅礼装", False), ("不识别", False),
])
def test_assist_all_tab_only_applies_to_servant_modes(tag_console, mode, enabled):
    browser, url, _directory = tag_console
    page = browser.new_page()
    page.goto(url)
    page.locator("#new-setting").click()
    raw = {"server": "CH", "assistMode": mode, "allNotSkip": True}
    page.locator("#preset-json").fill(json.dumps(raw))
    page.locator("#preset-assist-options summary").click()
    assert _toggle(page).is_enabled() == enabled
    playwright.expect(_toggle(page)).to_be_checked()
    assert _config(page) == raw
    page.locator("#cancel-preset").click()
    page.close()
