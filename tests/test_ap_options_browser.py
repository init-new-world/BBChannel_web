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

FIELDS = {"clearAP": "clear_ap", "allowOtherApple": "allow_other_apple"}


def _option(page, field):
    return page.locator(f'[data-run-option="{field}"]')


@pytest.mark.parametrize("width,height,locale", [(1440, 1000, "en-US"), (390, 844, "zh-CN")])
def test_ap_options_update_draft_and_saved_execution_plan(tag_console, width, height, locale):
    browser, url, directory = tag_console
    page = browser.new_page(viewport={"width": width, "height": height}, locale=locale)
    _entries, original = _seed(page, url)
    original.update({"clearAP": 1, "allowOtherApple": 0, "custom": {"keep": [1, 2]}})
    assert page.request.put(f"{url}/api/settings/demo", data={"config": original, "overwrite": True}).ok
    page.goto(url)
    page.locator("#edit-setting").click()
    playwright.expect(page.locator("#preset-ap-options")).to_be_attached(timeout=1000)
    assert not page.locator("#preset-ap-options").evaluate("e => e.open")
    page.locator("#preset-ap-options summary").click()
    playwright.expect(_option(page, "clearAP")).to_be_checked()
    playwright.expect(_option(page, "allowOtherApple")).not_to_be_checked()
    assert _config(page) == original
    _option(page, "clearAP").uncheck()
    _option(page, "allowOtherApple").check()
    playwright.expect(_option(page, "allowOtherApple")).to_be_focused()
    page.keyboard.press("Space")
    playwright.expect(_option(page, "allowOtherApple")).not_to_be_checked()
    page.keyboard.press("Space")
    expected = {**original, "clearAP": False, "allowOtherApple": True}
    assert _config(page) == expected
    assert page.request.get(f"{url}/api/settings/demo").json()["config"] == original
    if locale == "zh-CN":
        playwright.expect(page.locator("#preset-ap-options summary")).to_have_text("体力管理")
        playwright.expect(_option(page, "clearAP").locator("..")).to_contain_text("清空剩余体力")
        playwright.expect(_option(page, "allowOtherApple").locator("..")).to_contain_text("允许其他苹果")
    page.locator("#preset-ap-options").scroll_into_view_if_needed()
    page.screenshot(path=str(directory / f"ap-options-{width}.png"))
    assert page.locator(".preset-form").evaluate("e => e.scrollWidth <= e.clientWidth")
    page.locator("#save-preset").click()
    playwright.expect(page.locator("#preset-dialog")).not_to_be_visible()
    assert page.request.get(f"{url}/api/settings/demo").json()["config"] == expected
    run = page.request.get(f"{url}/api/settings/demo/plan").json()["run"]
    assert run["clear_ap"] is False
    assert run["allow_other_apple"] is True
    page.close()


@pytest.mark.parametrize("legacy", [[], {}, [0], {"enabled": False}, None, "false", 0, 1])
def test_ap_and_run_checkboxes_follow_execution_truth_without_coercing_legacy_values(tag_console, legacy):
    browser, url, _directory = tag_console
    page = browser.new_page()
    _entries, original = _seed(page, url)
    fields = [*FIELDS, "noChain", "firstBattleSet", "gameCrushRestart", "randomTouch", "noSpeedupSkill", "stuckRestart"]
    original.update(dict.fromkeys(fields, legacy))
    assert page.request.put(f"{url}/api/settings/demo", data={"config": original, "overwrite": True}).ok
    page.goto(url)
    page.locator("#edit-setting").click()
    page.locator("#preset-ap-options summary").click()
    page.locator("#preset-run-options summary").click()
    for field in fields:
        assert _option(page, field).is_checked() == bool(legacy)
    assert _config(page) == original
    _option(page, "allowOtherApple").click()
    expected = {**original, "allowOtherApple": not bool(legacy)}
    assert _config(page) == expected
    page.locator("#save-preset").click()
    playwright.expect(page.locator("#preset-dialog")).not_to_be_visible()
    saved = page.request.get(f"{url}/api/settings/demo").json()["config"]
    assert saved == expected
    assert type(saved["clearAP"]) is type(legacy)
    assert type(saved["allowOtherApple"]) is bool
    run = page.request.get(f"{url}/api/settings/demo/plan").json()["run"]
    assert run["clear_ap"] is bool(legacy)
    assert run["allow_other_apple"] is not bool(legacy)
    page.close()


def test_ap_defaults_do_not_write_keys_and_invalid_json_locks_controls(tag_console):
    browser, url, _directory = tag_console
    page = browser.new_page()
    _entries, original = _seed(page, url)
    page.goto(url)
    page.locator("#edit-setting").click()
    page.locator("#preset-ap-options summary").click()
    for field in FIELDS:
        playwright.expect(_option(page, field)).not_to_be_checked()
    assert _config(page) == original
    page.locator("#save-preset").click()
    playwright.expect(page.locator("#preset-dialog")).not_to_be_visible()
    assert page.request.get(f"{url}/api/settings/demo").json()["config"] == original
    page.locator("#edit-setting").click()
    page.locator("#preset-ap-options summary").click()
    _option(page, "clearAP").check()
    page.locator("#cancel-preset").click()
    assert page.request.get(f"{url}/api/settings/demo").json()["config"] == original
    page.locator("#edit-setting").click()
    page.locator("#preset-ap-options summary").click()
    for raw in ("{", "[]", "null", "1"):
        page.locator("#preset-json").fill(raw)
        for field in FIELDS:
            playwright.expect(_option(page, field)).to_be_disabled()
    page.locator("#preset-json").fill(json.dumps(original))
    for field in FIELDS:
        playwright.expect(_option(page, field)).to_be_enabled()
    page.locator("#cancel-preset").click()
    page.locator("#new-strategy").click()
    playwright.expect(page.locator("#preset-ap-options")).to_be_hidden()
    page.close()


def test_ap_controls_lock_during_preset_application_and_save(tag_console):
    browser, url, _directory = tag_console
    page = browser.new_page()
    _seed(page, url)
    page.goto(url)
    page.locator("#edit-setting").click()
    page.locator("#preset-ap-options summary").click()
    pending = []
    page.route("**/api/strategies/Preset", lambda route: pending.append(route))
    response = page.request.get(f"{url}/api/strategies/Preset")
    page.locator("#apply-turn-strategy").click()
    for field in FIELDS:
        playwright.expect(_option(page, field)).to_be_disabled()
    pending.pop().fulfill(response=response)
    for field in FIELDS:
        playwright.expect(_option(page, field)).to_be_enabled()
    page.route("**/api/settings/demo", lambda route: pending.append(route))
    page.locator("#save-preset").click()
    for field in FIELDS:
        playwright.expect(_option(page, field)).to_be_disabled()
    pending.pop().fulfill(status=500, json={"error": {"message": "Save failed"}})
    for field in FIELDS:
        playwright.expect(_option(page, field)).to_be_enabled()
    page.close()


def test_focused_ap_checkbox_survives_delayed_strategy_response(tag_console):
    browser, url, _directory = tag_console
    page = browser.new_page()
    _seed(page, url)
    response = page.request.get(f"{url}/api/strategies")
    pending = []
    page.route("**/api/strategies", lambda route: pending.append(route))
    page.goto(url)
    page.locator("#new-setting").click()
    page.locator("#preset-ap-options summary").click()
    _option(page, "clearAP").check()
    pending.pop().fulfill(response=response)
    playwright.expect(page.locator("#preset-strategy-source option[value='Preset']")).to_be_attached()
    playwright.expect(_option(page, "clearAP")).to_be_checked()
    playwright.expect(_option(page, "clearAP")).to_be_focused()
    assert _config(page)["clearAP"] is True
    page.keyboard.press("Space")
    assert _config(page)["clearAP"] is False
    page.close()


@pytest.mark.parametrize("flag", [[], {}])
@pytest.mark.parametrize("interval", [None, 0])
def test_disabled_legacy_watchdog_interval_does_not_block_ap_edits(tag_console, flag, interval):
    browser, url, _directory = tag_console
    page = browser.new_page()
    _entries, original = _seed(page, url)
    original.update({"stuckRestart": flag, "checkStuckInterval": interval})
    assert page.request.put(f"{url}/api/settings/demo", data={"config": original, "overwrite": True}).ok
    page.goto(url)
    page.locator("#edit-setting").click()
    page.locator("#preset-run-options summary").click()
    playwright.expect(_option(page, "stuckRestart")).not_to_be_checked(timeout=1000)
    playwright.expect(_option(page, "checkStuckInterval")).to_be_disabled()
    page.locator("#preset-ap-options summary").click()
    _option(page, "allowOtherApple").check()
    page.locator("#save-preset").click()
    playwright.expect(page.locator("#preset-dialog")).not_to_be_visible()
    saved = page.request.get(f"{url}/api/settings/demo").json()["config"]
    assert saved == {**original, "allowOtherApple": True}
    assert type(saved["stuckRestart"]) is type(flag)
    page.close()
