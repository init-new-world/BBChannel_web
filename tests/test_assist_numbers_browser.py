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

FIELDS = {"servantLevel": (1, 120, 90), "intervalAFswipeAssist": (0, 10, 0.25), "scrollLimit": (0, 1, 0.91)}


def _option(page, field):
    return page.locator(f'[data-assist-option="{field}"]')


@pytest.mark.parametrize("width,height,locale", [(1440, 1000, "en-US"), (390, 844, "zh-CN")])
def test_assist_numbers_preserve_defaults_and_update_saved_execution_plan(tag_console, width, height, locale):
    browser, url, directory = tag_console
    page = browser.new_page(viewport={"width": width, "height": height}, locale=locale)
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    _entries, original = _seed(page, url)
    page.goto(url)
    page.locator("#edit-setting").click()
    page.locator("#preset-assist-options summary").click()
    for field, default in {"servantLevel": "1", "intervalAFswipeAssist": "0.5", "scrollLimit": "0.96"}.items():
        playwright.expect(_option(page, field)).to_have_value(default, timeout=2000)
    assert _config(page) == original
    for field, (_minimum, _maximum, replacement) in FIELDS.items():
        _option(page, field).fill(str(replacement))
        _option(page, field).press("Tab")
    expected = {**original, **{field: values[2] for field, values in FIELDS.items()}}
    assert _config(page) == expected
    assert page.request.get(f"{url}/api/settings/demo").json()["config"] == original
    if locale == "zh-CN":
        playwright.expect(_option(page, "servantLevel").locator("..")).to_contain_text("从者最低等级")
        playwright.expect(_option(page, "intervalAFswipeAssist").locator("..")).to_contain_text("滑动后等待")
        playwright.expect(_option(page, "scrollLimit").locator("..")).to_contain_text("滚动边界")
    page.locator("#preset-assist-options").scroll_into_view_if_needed()
    page.screenshot(path=str(directory / f"assist-numbers-{width}.png"))
    assert page.locator(".preset-form").evaluate("e => e.scrollWidth <= e.clientWidth")
    page.locator("#save-preset").click()
    playwright.expect(page.locator("#preset-dialog")).not_to_be_visible()
    assert page.request.get(f"{url}/api/settings/demo").json()["config"] == expected
    assist = page.request.get(f"{url}/api/settings/demo/plan").json()["assist"]
    assert assist["servant_level"] == 90
    assert assist["interval_after_swipe"] == 0.25
    assert assist["scroll_limit"] == 0.91
    assert errors == []
    page.close()


@pytest.mark.parametrize("field,invalid", [
    ("servantLevel", "121"), ("servantLevel", "90.5"),
    ("intervalAFswipeAssist", "11"), ("intervalAFswipeAssist", ""),
    ("scrollLimit", "1.1"), ("scrollLimit", "-0.1"),
])
def test_invalid_assist_number_survives_other_edits_and_blocks_save(tag_console, field, invalid):
    browser, url, _directory = tag_console
    page = browser.new_page()
    _entries, original = _seed(page, url)
    page.goto(url)
    page.locator("#edit-setting").click()
    page.locator("#preset-assist-options summary").click()
    number = _option(page, field)
    number.fill(invalid)
    number.press("Tab")
    _option(page, "onlyFriendAssist").check()
    _option(page, "assistMode").select_option("不识别")
    playwright.expect(number).to_have_value(invalid)
    playwright.expect(number).to_be_enabled()
    assert not number.evaluate("e => e.checkValidity()")
    assert _config(page) == {**original, "onlyFriendAssist": True, "assistMode": "不识别"}
    page.locator("#preset-assist-options summary").click()
    page.locator("#save-preset").click()
    playwright.expect(page.locator("#preset-dialog")).to_be_visible()
    assert page.locator("#preset-assist-options").evaluate("e => e.open")
    assert page.request.get(f"{url}/api/settings/demo").json()["config"] == original
    page.locator("#preset-json").fill(json.dumps(original))
    assert number.evaluate("e => e.checkValidity()")
    page.locator("#save-preset").click()
    playwright.expect(page.locator("#preset-dialog")).not_to_be_visible()
    assert page.request.get(f"{url}/api/settings/demo").json()["config"] == original
    page.close()


@pytest.mark.parametrize("value", [None, "90", [], {}, 121, 1.5, True])
def test_legacy_assist_number_is_preserved_until_explicit_edit(tag_console, value):
    browser, url, _directory = tag_console
    page = browser.new_page()
    page.goto(url)
    page.locator("#new-setting").click()
    page.locator("#preset-name").fill("LegacyNumbers")
    raw = {"server": "CH", "round1_turns": 1, "assistMode": "从者礼装", **dict.fromkeys(FIELDS, value)}
    page.locator("#preset-json").fill(json.dumps(raw))
    page.locator("#preset-assist-options summary").click()
    for field, (minimum, maximum, _replacement) in FIELDS.items():
        valid = type(value) in (int, float) and minimum <= value <= maximum and (field != "servantLevel" or value == int(value))
        if valid:
            playwright.expect(_option(page, field)).to_have_value(str(value))
        else:
            playwright.expect(_option(page, field)).to_have_value("")
            playwright.expect(_option(page, field)).to_have_attribute("title", f"{json.dumps(value, separators=(',', ':'))} (current)")
    assert _config(page) == raw
    page.locator("#save-preset").click()
    playwright.expect(page.locator("#preset-dialog")).not_to_be_visible()
    assert page.request.get(f"{url}/api/settings/LegacyNumbers").json()["config"] == raw
    page.locator("#setting-select").select_option("LegacyNumbers")
    page.locator("#edit-setting").click()
    page.locator("#preset-assist-options summary").click()
    for field, (_minimum, _maximum, replacement) in FIELDS.items():
        _option(page, field).fill(str(replacement))
        _option(page, field).press("Tab")
    assert _config(page) == {**raw, **{field: values[2] for field, values in FIELDS.items()}}
    page.close()


@pytest.mark.parametrize("mode,servant,search", [
    ("从者礼装", True, True), ("仅从者", True, True), ("冠位助战", True, True),
    ("仅礼装", False, True), ("冠位助战仅礼装", False, True), ("不识别", False, False),
])
def test_assist_number_mode_gates_do_not_clear_values(tag_console, mode, servant, search):
    browser, url, _directory = tag_console
    page = browser.new_page()
    page.goto(url)
    page.locator("#new-setting").click()
    raw = {"server": "CH", "assistMode": mode, **{field: values[2] for field, values in FIELDS.items()}}
    page.locator("#preset-json").fill(json.dumps(raw))
    page.locator("#preset-assist-options summary").click()
    assert _option(page, "servantLevel").is_enabled() == servant
    for field in ("intervalAFswipeAssist", "scrollLimit"):
        assert _option(page, field).is_enabled() == search
    assert _config(page) == raw
    page.close()


def test_partial_assist_number_survives_pending_strategy_list_and_other_controls(tag_console):
    browser, url, _directory = tag_console
    page = browser.new_page()
    _seed(page, url)
    response = page.request.get(f"{url}/api/strategies")
    pending = []
    page.route("**/api/strategies", lambda route: pending.append(route))
    page.goto(url)
    page.locator("#new-setting").click()
    page.locator("#preset-assist-options summary").click()
    number = _option(page, "intervalAFswipeAssist")
    number.fill("")
    number.press_sequentially("1e")
    assert number.evaluate("e => e.validity.badInput")
    pending.pop().fulfill(response=response)
    playwright.expect(page.locator("#preset-strategy-source option[value='Preset']")).to_be_attached()
    assert number.evaluate("e => e.validity.badInput")
    playwright.expect(number).to_be_focused()
    _option(page, "fullEquip").check()
    assert number.evaluate("e => e.validity.badInput")
    number.click()
    number.press("End")
    number.press_sequentially("1")
    number.press("Tab")
    playwright.expect(number).to_have_value("10")
    assert _config(page)["intervalAFswipeAssist"] == 10
    page.close()


@pytest.mark.parametrize("field,invalid,replacement", [
    ("servantLevel", "121", "90"), ("scrollLimit", "1.1", "0.96"),
    ("intervalAFswipeAssist", "11", "0.25"),
])
def test_invalid_number_stays_editable_through_complete_correction_after_mode_change(
    tag_console, field, invalid, replacement,
):
    browser, url, _directory = tag_console
    page = browser.new_page()
    _seed(page, url)
    page.goto(url)
    page.locator("#edit-setting").click()
    page.locator("#preset-assist-options summary").click()
    number = _option(page, field)
    number.fill(invalid)
    _option(page, "assistMode").select_option("不识别")
    playwright.expect(number).to_be_enabled()
    number.fill("")
    number.press_sequentially(replacement)
    playwright.expect(number).to_have_value(replacement, timeout=2000)
    playwright.expect(number).to_be_enabled()
    number.press("Tab")
    playwright.expect(number).to_be_disabled()
    assert _config(page)[field] == float(replacement)
    page.locator("#save-preset").click()
    playwright.expect(page.locator("#preset-dialog")).not_to_be_visible()
    assert page.request.get(f"{url}/api/settings/demo").json()["config"][field] == float(replacement)
    page.close()


def test_valid_focused_number_survives_delayed_strategy_response(tag_console):
    browser, url, _directory = tag_console
    page = browser.new_page()
    _seed(page, url)
    response = page.request.get(f"{url}/api/strategies")
    pending = []
    page.route("**/api/strategies", lambda route: pending.append(route))
    page.goto(url)
    page.locator("#new-setting").click()
    page.locator("#preset-assist-options summary").click()
    number = _option(page, "intervalAFswipeAssist")
    number.fill("0.25")
    playwright.expect(number).to_be_focused()
    pending.pop().fulfill(response=response)
    playwright.expect(page.locator("#preset-strategy-source option[value='Preset']")).to_be_attached()
    playwright.expect(number).to_have_value("0.25")
    playwright.expect(number).to_be_focused()
    assert _config(page)["intervalAFswipeAssist"] == 0.25
    page.close()


def test_assist_numbers_lock_during_pending_requests_and_recover_on_failure(tag_console):
    browser, url, _directory = tag_console
    page = browser.new_page()
    _entries, original = _seed(page, url)
    page.goto(url)
    page.locator("#edit-setting").click()
    page.locator("#preset-assist-options summary").click()
    pending = []
    page.route("**/api/strategies/Preset", lambda route: pending.append(route))
    page.locator("#apply-turn-strategy").click()
    for field in FIELDS:
        playwright.expect(_option(page, field)).to_be_disabled()
    pending.pop().fulfill(status=500, json={"error": {"message": "Load failed"}})
    for field in FIELDS:
        playwright.expect(_option(page, field)).to_be_enabled()
    assert _config(page) == original
    page.route("**/api/settings/demo", lambda route: pending.append(route))
    page.locator("#save-preset").click()
    for field in FIELDS:
        playwright.expect(_option(page, field)).to_be_disabled()
    pending.pop().fulfill(status=500, json={"error": {"message": "Save failed"}})
    for field in FIELDS:
        playwright.expect(_option(page, field)).to_be_enabled()
    assert _config(page) == original
    page.close()
