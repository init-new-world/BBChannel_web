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


def _option(page, field):
    return page.locator(f'[data-assist-option="{field}"]')


@pytest.mark.parametrize("width,height", [(1440, 1000), (390, 844)])
def test_edit_assist_options_preserves_script_and_updates_saved_plan(tag_console, width, height):
    browser, url, directory = tag_console
    page = browser.new_page(viewport={"width": width, "height": height})
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    _entries, original = _seed(page, url)
    page.goto(url)
    page.locator("#edit-setting").click()
    page.locator("#preset-assist-options summary").click()
    playwright.expect(_option(page, "assistMode")).to_have_value("仅从者")
    assert _config(page) == original
    _option(page, "assistMode").select_option("冠位助战")
    _option(page, "NPlevel").select_option("3")
    _option(page, "jbType").select_option("NP50")
    for field in ("fullEquip", "onlyFriendAssist", "noGrandRefresh"):
        _option(page, field).check()
    expected = {**original, "assistMode": "冠位助战", "NPlevel": 3, "jbType": "NP50",
                "fullEquip": True, "onlyFriendAssist": True, "noGrandRefresh": True}
    assert _config(page) == expected
    assert page.request.get(f"{url}/api/settings/demo").json()["config"] == original
    page.locator("#preset-assist-options").scroll_into_view_if_needed()
    page.screenshot(path=str(directory / f"assist-options-{width}.png"))
    assert page.locator(".preset-form").evaluate("e => e.scrollWidth <= e.clientWidth")
    page.locator("#save-preset").click()
    playwright.expect(page.locator("#preset-dialog")).not_to_be_visible()
    assert page.request.get(f"{url}/api/settings/demo").json()["config"] == expected
    assist = page.request.get(f"{url}/api/settings/demo/plan").json()["assist"]
    assert assist["mode"] == "冠位助战"
    assert assist["np_level"] == 3
    assert assist["bond_equip_type"] == "NP50"
    assert assist["full_limit_break"] is True
    assert assist["friend_only"] is True
    assert assist["no_grand_refresh"] is True
    assert errors == []
    page.close()


@pytest.mark.parametrize("mode,servant,equip,grand", [
    ("从者礼装", True, True, False),
    ("仅从者", True, False, False),
    ("仅礼装", False, True, False),
    ("不识别", False, False, False),
    ("冠位助战", True, True, True),
    ("冠位助战仅礼装", False, True, True),
])
def test_mode_enables_only_applicable_controls_without_clearing_values(tag_console, mode, servant, equip, grand):
    browser, url, _directory = tag_console
    page = browser.new_page()
    page.goto(url)
    page.locator("#new-setting").click()
    raw = {"server": "CH", "assistMode": "冠位助战", "NPlevel": 4, "jbType": "初始",
           "fullEquip": True, "onlyFriendAssist": True, "noGrandRefresh": True,
           "assistEquip": [["Legacy", "Nested"]], "skillsLevel": [1, 2, 3], "custom": {"keep": True}}
    page.locator("#preset-json").fill(json.dumps(raw))
    page.locator("#preset-assist-options summary").click()
    _option(page, "assistMode").select_option(mode)
    assert _config(page) == {**raw, "assistMode": mode}
    for field, enabled in [("onlyFriendAssist", servant), ("NPlevel", servant), ("fullEquip", equip),
                           ("noGrandRefresh", grand), ("jbType", grand)]:
        assert _option(page, field).is_enabled() == enabled
    _option(page, "assistMode").select_option("冠位助战")
    playwright.expect(_option(page, "NPlevel")).to_have_value("4")
    playwright.expect(_option(page, "jbType")).to_have_value("初始")
    for field in ("fullEquip", "onlyFriendAssist", "noGrandRefresh"):
        playwright.expect(_option(page, field)).to_be_checked()
    assert _config(page) == raw
    page.close()


def test_unknown_and_null_assist_values_remain_until_explicitly_replaced(tag_console):
    browser, url, _directory = tag_console
    page = browser.new_page()
    page.goto(url)
    page.locator("#new-setting").click()
    raw = {"server": "CH", "assistMode": "Future mode", "NPlevel": "3", "jbType": None, "custom": 1}
    page.locator("#preset-json").fill(json.dumps(raw))
    page.locator("#preset-assist-options summary").click()
    playwright.expect(_option(page, "assistMode").locator("option:checked")).to_contain_text("Future mode")
    playwright.expect(_option(page, "NPlevel").locator("option:checked")).to_contain_text("current")
    assert _config(page) == raw
    playwright.expect(_option(page, "NPlevel")).to_be_disabled()
    _option(page, "assistMode").select_option("冠位助战")
    _option(page, "fullEquip").check()
    assert _config(page) == {**raw, "assistMode": "冠位助战", "fullEquip": True}
    for field in ("NPlevel", "jbType"):
        select = _option(page, field)
        select.focus()
        select.press("Space")
        select.press("Home")
        select.press("Enter")
    expected = {**raw, "assistMode": "冠位助战", "fullEquip": True, "NPlevel": 1, "jbType": "任意"}
    assert _config(page) == expected
    page.locator("#preset-json").fill("{")
    playwright.expect(_option(page, "assistMode")).to_be_disabled()
    page.locator("#preset-json").fill("[]")
    playwright.expect(_option(page, "assistMode")).to_be_disabled()
    page.locator("#preset-json").fill(json.dumps({"server": "CH"}))
    playwright.expect(_option(page, "assistMode")).to_have_value("从者礼装")
    playwright.expect(_option(page, "NPlevel")).to_have_value("1")
    assert _config(page) == {"server": "CH"}
    page.close()


def test_assist_controls_keep_focus_and_other_invalid_drafts(tag_console):
    browser, url, _directory = tag_console
    page = browser.new_page()
    page.goto(url)
    page.locator("#new-setting").click()
    page.locator("#preset-assist-options summary").click()
    friend = _option(page, "onlyFriendAssist")
    friend.click()
    playwright.expect(friend).to_be_focused()
    friend.press("Space")
    playwright.expect(friend).not_to_be_checked()
    skill = page.locator('[data-assist-skill-index="0"]')
    skill.fill("11")
    skill.press("Tab")
    page.locator("#preset-run-options summary").click()
    page.locator('[data-run-option="stuckRestart"]').check()
    interval = page.locator('[data-run-option="checkStuckInterval"]')
    interval.fill("")
    interval.press_sequentially("1e")
    interval.press("Tab")
    _option(page, "assistMode").select_option("仅从者")
    _option(page, "NPlevel").select_option("2")
    playwright.expect(skill).to_have_value("11")
    assert interval.evaluate("e => e.validity.badInput")
    page.locator("#cancel-preset").click()
    page.locator("#new-strategy").click()
    playwright.expect(page.locator("#preset-assist-options")).to_be_hidden()
    page.close()


def test_assist_controls_lock_during_preset_load_and_save(tag_console):
    browser, url, _directory = tag_console
    page = browser.new_page()
    _seed(page, url)
    page.goto(url)
    page.locator("#edit-setting").click()
    page.locator("#preset-assist-options summary").click()
    pending = []
    page.route("**/api/strategies/Preset", lambda route: pending.append(route))
    response = page.request.get(f"{url}/api/strategies/Preset")
    page.locator("#apply-turn-strategy").click()
    playwright.expect(_option(page, "assistMode")).to_be_disabled()
    pending.pop().fulfill(response=response)
    playwright.expect(_option(page, "assistMode")).to_be_enabled()
    page.route("**/api/settings/demo", lambda route: pending.append(route))
    page.locator("#save-preset").click()
    playwright.expect(_option(page, "assistMode")).to_be_disabled()
    pending.pop().fulfill(status=500, json={"error": {"message": "Save failed"}})
    playwright.expect(_option(page, "assistMode")).to_be_enabled()
    page.close()


@pytest.mark.parametrize("value", [[], {}, [0], {"enabled": False}, None, "false"])
def test_legacy_checkbox_display_matches_saved_plan_without_coercing_source(tag_console, value):
    browser, url, _directory = tag_console
    page = browser.new_page()
    page.goto(url)
    page.locator("#new-setting").click()
    page.locator("#preset-name").fill("LegacyFlags")
    fields = {"fullEquip": "full_limit_break", "onlyFriendAssist": "friend_only", "noGrandRefresh": "no_grand_refresh"}
    raw = {"server": "CH", "round1_turns": 1, "assistMode": "冠位助战", **dict.fromkeys(fields, value)}
    page.locator("#preset-json").fill(json.dumps(raw))
    page.locator("#preset-assist-options summary").click()
    for field in fields:
        assert _option(page, field).is_checked() == bool(value)
    assert _config(page) == raw
    page.locator("#save-preset").click()
    playwright.expect(page.locator("#preset-dialog")).not_to_be_visible()
    assert page.request.get(f"{url}/api/settings/LegacyFlags").json()["config"] == raw
    assist = page.request.get(f"{url}/api/settings/LegacyFlags/plan").json()["assist"]
    assert all(assist[key] == bool(value) for key in fields.values())
    page.locator("#edit-setting").click()
    page.locator("#preset-assist-options summary").click()
    _option(page, "fullEquip").click()
    assert _config(page) == {**raw, "fullEquip": not bool(value)}
    page.close()
