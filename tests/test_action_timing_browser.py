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

FIELDS = {"intervalBF": (0, 0.25), "intervalAF": (0.1, 0.35), "intervalBFchooseCard": (0.5, 0.75)}


def _option(page, field):
    return page.locator(f'[data-run-option="{field}"]')


@pytest.mark.parametrize("width,height,locale", [(1440, 1000, "en-US"), (390, 844, "zh-CN")])
def test_action_timing_defaults_are_draft_only_and_save_to_execution_plan(tag_console, width, height, locale):
    browser, url, directory = tag_console
    page = browser.new_page(viewport={"width": width, "height": height}, locale=locale)
    _entries, original = _seed(page, url)
    page.goto(url)
    page.locator("#edit-setting").click()
    page.locator("#preset-operation-timing summary").click()
    for field, (default, _replacement) in FIELDS.items():
        playwright.expect(_option(page, field)).to_have_value(str(default), timeout=2000)
    assert _config(page) == original
    for field, (_default, replacement) in FIELDS.items():
        _option(page, field).fill(str(replacement))
        _option(page, field).press("Tab")
    expected = {**original, **{field: values[1] for field, values in FIELDS.items()}}
    assert _config(page) == expected
    assert page.request.get(f"{url}/api/settings/demo").json()["config"] == original
    if locale == "zh-CN":
        playwright.expect(_option(page, "intervalBF").locator("..")).to_contain_text("操作前延时")
        playwright.expect(_option(page, "intervalAF").locator("..")).to_contain_text("操作后延时")
        playwright.expect(_option(page, "intervalBFchooseCard").locator("..")).to_contain_text("选卡识别前等待")
    page.locator("#preset-operation-timing").scroll_into_view_if_needed()
    page.screenshot(path=str(directory / f"action-timing-{width}.png"))
    assert page.locator(".preset-form").evaluate("e => e.scrollWidth <= e.clientWidth")
    page.locator("#save-preset").click()
    playwright.expect(page.locator("#preset-dialog")).not_to_be_visible()
    run = page.request.get(f"{url}/api/settings/demo/plan").json()["run"]
    assert run["interval_before_operation"] == 0.25
    assert run["interval_after_operation"] == 0.35
    assert run["interval_before_choose_card"] == 0.75
    page.close()


@pytest.mark.parametrize("field,invalid", [
    ("intervalBF", "11"), ("intervalAF", "0"), ("intervalBFchooseCard", "-1"),
    ("intervalBF", ""), ("intervalBFchooseCard", ""),
])
def test_invalid_action_timing_stays_visible_and_blocks_save(tag_console, field, invalid):
    browser, url, _directory = tag_console
    page = browser.new_page()
    _entries, original = _seed(page, url)
    page.goto(url)
    page.locator("#edit-setting").click()
    page.locator("#preset-operation-timing summary").click()
    number = _option(page, field)
    number.fill(invalid)
    number.press("Tab")
    page.locator("#preset-run-options summary").click()
    _option(page, "randomTouch").check()
    page.locator("#preset-assist-options summary").click()
    page.locator('[data-assist-option="onlyFriendAssist"]').check()
    playwright.expect(number).to_have_value(invalid)
    assert not number.evaluate("e => e.checkValidity()")
    assert field not in _config(page)
    page.locator("#preset-operation-timing summary").click()
    page.locator("#save-preset").click()
    playwright.expect(page.locator("#preset-dialog")).to_be_visible()
    assert page.locator("#preset-operation-timing").evaluate("e => e.open")
    assert page.request.get(f"{url}/api/settings/demo").json()["config"] == original
    page.locator("#preset-json").fill(json.dumps(original))
    assert number.evaluate("e => e.checkValidity()")
    page.locator("#save-preset").click()
    playwright.expect(page.locator("#preset-dialog")).not_to_be_visible()
    page.close()


@pytest.mark.parametrize("legacy", [None, "0.2", {}, 30, -1, True, 0])
def test_action_timing_legacy_values_are_not_coerced_on_load_or_save(tag_console, legacy):
    browser, url, _directory = tag_console
    page = browser.new_page()
    page.goto(url)
    page.locator("#new-setting").click()
    page.locator("#preset-name").fill("LegacyTiming")
    raw = {"server": "CH", "round1_turns": 1, **dict.fromkeys(FIELDS, legacy)}
    page.locator("#preset-json").fill(json.dumps(raw))
    page.locator("#preset-operation-timing summary").click()
    for field in FIELDS:
        if legacy == 0 and type(legacy) is int and field != "intervalAF":
            playwright.expect(_option(page, field)).to_have_value("0")
        else:
            playwright.expect(_option(page, field)).to_have_value("")
            playwright.expect(_option(page, field)).to_have_attribute("title", f"{json.dumps(legacy)} (current)")
    assert _config(page) == raw
    page.locator("#save-preset").click()
    playwright.expect(page.locator("#preset-dialog")).not_to_be_visible()
    assert page.request.get(f"{url}/api/settings/LegacyTiming").json()["config"] == raw
    page.close()


def test_focused_action_timing_survives_async_render_and_partial_number(tag_console):
    browser, url, _directory = tag_console
    page = browser.new_page()
    _seed(page, url)
    response = page.request.get(f"{url}/api/strategies")
    pending = []
    page.route("**/api/strategies", lambda route: pending.append(route))
    page.goto(url)
    page.locator("#new-setting").click()
    page.locator("#preset-operation-timing summary").click()
    number = _option(page, "intervalBFchooseCard")
    number.fill("0.75")
    pending.pop().fulfill(response=response)
    playwright.expect(page.locator("#preset-strategy-source option[value='Preset']")).to_be_attached()
    playwright.expect(number).to_have_value("0.75")
    playwright.expect(number).to_be_focused()
    assert _config(page)["intervalBFchooseCard"] == 0.75
    number.fill("")
    number.press_sequentially("1e")
    page.locator("#preset-run-options summary").click()
    _option(page, "randomTouch").check()
    assert number.evaluate("e => e.validity.badInput")
    number.click()
    number.press("End")
    number.press_sequentially("1")
    number.press("Tab")
    playwright.expect(number).to_have_value("10")
    assert _config(page)["intervalBFchooseCard"] == 10
    page.close()


@pytest.mark.parametrize("field", FIELDS)
def test_focused_valid_timing_can_submit_with_enter_without_blurring(tag_console, field):
    browser, url, _directory = tag_console
    page = browser.new_page()
    _entries, original = _seed(page, url)
    page.goto(url)
    page.locator("#edit-setting").click()
    page.locator("#preset-operation-timing summary").click()
    number = _option(page, field)
    replacement = FIELDS[field][1]
    number.fill(str(replacement))
    playwright.expect(number).to_be_focused()
    number.press("Enter")
    playwright.expect(page.locator("#preset-dialog")).not_to_be_visible()
    assert page.request.get(f"{url}/api/settings/demo").json()["config"] == {**original, field: replacement}
    page.close()
