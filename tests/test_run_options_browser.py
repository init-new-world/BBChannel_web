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
    return page.locator(f'[data-run-option="{field}"]')


@pytest.mark.parametrize("width,height", [(1440, 1000), (390, 844)])
def test_randomization_options_are_draft_only_and_update_execution_plan(tag_console, width, height):
    browser, url, directory = tag_console
    page = browser.new_page(viewport={"width": width, "height": height})
    page.set_default_timeout(10000)
    _entries, original = _seed(page, url)
    original.update({"randomTouch": 1, "randomTime": 0.4})
    assert page.request.put(f"{url}/api/settings/demo", data={"config": original, "overwrite": True}).ok
    page.goto(url)
    page.locator("#edit-setting").click()
    page.locator("#preset-run-options summary").click()
    touch = _option(page, "randomTouch")
    delay = _option(page, "randomTime")
    playwright.expect(touch).to_be_checked()
    playwright.expect(delay).to_have_value("0.4")
    assert _config(page) == original
    touch.uncheck()
    delay.fill("2.25")
    delay.press("Tab")
    expected = {**original, "randomTouch": False, "randomTime": 2.25}
    assert _config(page) == expected
    assert page.request.get(f"{url}/api/settings/demo").json()["config"] == original
    page.locator("#preset-run-options summary").focus()
    page.locator("#preset-run-options").scroll_into_view_if_needed()
    page.screenshot(path=str(directory / f"run-randomization-{width}.png"))
    assert page.locator(".preset-form").evaluate("e => e.scrollWidth <= e.clientWidth")
    page.locator("#save-preset").click()
    playwright.expect(page.locator("#preset-dialog")).not_to_be_visible()
    assert page.request.get(f"{url}/api/settings/demo").json()["config"] == expected
    run = page.request.get(f"{url}/api/settings/demo/plan").json()["run"]
    assert run["random_touch"] is False
    assert run["random_time"] == 2.25
    page.close()


@pytest.mark.parametrize("width,height", [(1440, 1000), (390, 844)])
def test_battle_settings_and_skill_speedup_options_update_plan(tag_console, width, height):
    browser, url, directory = tag_console
    page = browser.new_page(viewport={"width": width, "height": height})
    page.set_default_timeout(10000)
    _entries, original = _seed(page, url)
    original.update({"firstBattleSet": 1, "noSpeedupSkill": 0})
    assert page.request.put(f"{url}/api/settings/demo", data={"config": original, "overwrite": True}).ok
    page.goto(url)
    page.locator("#edit-setting").click()
    page.locator("#preset-run-options summary").click()
    setup = _option(page, "firstBattleSet")
    speedup = _option(page, "noSpeedupSkill")
    playwright.expect(setup).to_be_checked()
    playwright.expect(speedup).not_to_be_checked()
    assert _config(page) == original
    setup.uncheck()
    speedup.check()
    expected = {**original, "firstBattleSet": False, "noSpeedupSkill": True}
    assert _config(page) == expected
    assert page.request.get(f"{url}/api/settings/demo").json()["config"] == original
    page.locator("#preset-run-options summary").focus()
    page.locator("#preset-run-options").scroll_into_view_if_needed()
    page.screenshot(path=str(directory / f"run-battle-settings-{width}.png"))
    assert page.locator(".preset-form").evaluate("e => e.scrollWidth <= e.clientWidth")
    page.locator("#save-preset").click()
    playwright.expect(page.locator("#preset-dialog")).not_to_be_visible()
    assert page.request.get(f"{url}/api/settings/demo").json()["config"] == expected
    run = page.request.get(f"{url}/api/settings/demo/plan").json()["run"]
    assert run["first_battle_set"] is False
    assert run["no_speedup_skill"] is True
    page.close()


def test_new_battle_option_checkboxes_default_off_and_keep_keyboard_focus(tag_console):
    browser, url, _directory = tag_console
    page = browser.new_page()
    page.goto(url)
    page.locator("#new-setting").click()
    page.locator("#preset-run-options summary").click()
    setup = _option(page, "firstBattleSet")
    speedup = _option(page, "noSpeedupSkill")
    playwright.expect(setup).not_to_be_checked()
    playwright.expect(speedup).not_to_be_checked()
    assert "firstBattleSet" not in _config(page)
    setup.click()
    playwright.expect(setup).to_be_focused()
    page.keyboard.press("Space")
    playwright.expect(setup).not_to_be_checked()
    assert _config(page)["firstBattleSet"] is False
    speedup.check()
    assert _config(page)["noSpeedupSkill"] is True
    page.close()


def test_random_time_invalid_draft_survives_other_edits_and_blocks_save(tag_console):
    browser, url, _directory = tag_console
    page = browser.new_page()
    page.set_default_timeout(10000)
    _entries, original = _seed(page, url)
    page.goto(url)
    page.locator("#edit-setting").click()
    page.locator("#preset-run-options summary").click()
    delay = _option(page, "randomTime")
    playwright.expect(delay).to_have_value("0")
    assert _config(page) == original
    delay.fill("11")
    delay.press("Tab")
    _option(page, "randomTouch").check()
    page.locator("#preset-team summary").click()
    page.locator('[data-team-used="4"]').check()
    playwright.expect(delay).to_have_value("11")
    assert not delay.evaluate("e => e.checkValidity()")
    page.locator("#preset-run-options summary").click()
    page.locator("#save-preset").click()
    playwright.expect(page.locator("#preset-dialog")).to_be_visible()
    assert page.locator("#preset-run-options").evaluate("e => e.open")
    assert page.request.get(f"{url}/api/settings/demo").json()["config"] == original
    delay.fill("0")
    delay.press("Tab")
    assert _config(page)["randomTime"] == 0
    page.locator("#save-preset").click()
    playwright.expect(page.locator("#preset-dialog")).not_to_be_visible()
    page.close()


def test_incomplete_random_wait_survives_unrelated_controls(tag_console):
    browser, url, _directory = tag_console
    page = browser.new_page()
    page.goto(url)
    page.locator("#new-setting").click()
    page.locator("#preset-run-options summary").click()
    delay = _option(page, "randomTime")
    delay.fill("")
    delay.press_sequentially("1e")
    delay.press("Tab")
    assert delay.evaluate("e => e.validity.badInput")
    _option(page, "randomTouch").check()
    assert delay.evaluate("e => e.validity.badInput")
    assert "randomTime" not in _config(page)
    delay.click()
    delay.press("End")
    delay.press_sequentially("1")
    delay.press("Tab")
    playwright.expect(delay).to_have_value("10")
    assert _config(page)["randomTime"] == 10
    page.close()


@pytest.mark.parametrize("invalid", [None, "2", {"future": 1}])
def test_malformed_random_time_requires_explicit_correction(tag_console, invalid):
    browser, url, _directory = tag_console
    page = browser.new_page()
    page.set_default_timeout(10000)
    _entries, original = _seed(page, url)
    page.goto(url)
    page.locator("#edit-setting").click()
    raw = {**original, "randomTime": invalid}
    page.locator("#preset-json").fill(json.dumps(raw))
    page.locator("#preset-run-options summary").click()
    delay = _option(page, "randomTime")
    playwright.expect(delay).to_have_value("")
    _option(page, "randomTouch").check()
    assert _config(page) == {**raw, "randomTouch": True}
    page.locator("#save-preset").click()
    playwright.expect(page.locator("#preset-dialog")).to_be_visible()
    assert page.request.get(f"{url}/api/settings/demo").json()["config"] == original
    delay.fill("10")
    delay.press("Tab")
    assert _config(page)["randomTime"] == 10
    page.locator("#save-preset").click()
    playwright.expect(page.locator("#preset-dialog")).not_to_be_visible()
    page.close()


@pytest.mark.parametrize("width,height", [(1440, 1000), (390, 844)])
def test_edit_run_options_preserves_script_and_updates_execution_plan(tag_console, width, height):
    browser, url, directory = tag_console
    page = browser.new_page(viewport={"width": width, "height": height})
    page.set_default_timeout(10000)
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    _entries, original = _seed(page, url)
    page.goto(url)
    page.locator("#edit-setting").click()
    page.locator("#preset-run-options summary").click()
    interval = _option(page, "checkStuckInterval")
    playwright.expect(interval).to_have_value("30")
    playwright.expect(interval).to_be_disabled()
    for field in ("noChain", "gameCrushRestart", "stuckRestart"):
        _option(page, field).check()
    interval.fill("45.5")
    interval.press("Tab")
    expected = {**original, "noChain": True, "gameCrushRestart": True, "stuckRestart": True, "checkStuckInterval": 45.5}
    assert _config(page) == expected
    assert page.request.get(f"{url}/api/settings/demo").json()["config"] == original
    page.locator("#preset-run-options").scroll_into_view_if_needed()
    page.screenshot(path=str(directory / f"run-options-{width}.png"))
    assert page.locator(".preset-form").evaluate("e => e.scrollWidth <= e.clientWidth")
    page.locator("#save-preset").click()
    playwright.expect(page.locator("#preset-dialog")).not_to_be_visible()
    assert page.request.get(f"{url}/api/settings/demo").json()["config"] == expected
    run = page.request.get(f"{url}/api/settings/demo/plan").json()["run"]
    assert run["no_chain"] is True
    assert run["game_crash_restart"] is True
    assert run["stuck_restart"] is True
    assert run["check_stuck_interval"] == 45.5
    assert errors == []
    page.close()


def test_invalid_run_option_draft_survives_other_edits_and_reopens_on_save(tag_console):
    browser, url, _directory = tag_console
    page = browser.new_page()
    page.set_default_timeout(10000)
    _entries, original = _seed(page, url)
    page.goto(url)
    page.locator("#edit-setting").click()
    page.locator("#preset-run-options summary").click()
    _option(page, "stuckRestart").check()
    interval = _option(page, "checkStuckInterval")
    interval.fill("0")
    interval.press("Tab")
    _option(page, "noChain").check()
    page.locator('[data-turn-np-index="0"]').select_option("3")
    page.locator("#preset-waves summary").click()
    page.locator('[data-script-wave="1"] [data-wave-action="add-turn"]').click()
    _option(page, "stuckRestart").uncheck()
    playwright.expect(interval).to_have_value("0")
    playwright.expect(interval).to_be_enabled()
    assert not interval.evaluate("e => e.checkValidity()")
    page.locator("#preset-run-options summary").click()
    page.locator("#save-preset").click()
    playwright.expect(page.locator("#preset-dialog")).to_be_visible()
    assert page.locator("#preset-run-options").evaluate("e => e.open")
    assert page.request.get(f"{url}/api/settings/demo").json()["config"] == original
    page.locator("#preset-json").fill(json.dumps(original))
    playwright.expect(interval).to_have_value("30")
    playwright.expect(interval).to_be_disabled()
    page.locator("#save-preset").click()
    playwright.expect(page.locator("#preset-dialog")).not_to_be_visible()
    page.close()


def test_run_options_are_locked_during_pending_preset_load(tag_console):
    browser, url, _directory = tag_console
    page = browser.new_page()
    page.set_default_timeout(10000)
    _seed(page, url)
    page.goto(url)
    page.locator("#edit-setting").click()
    page.locator("#preset-run-options summary").click()
    pending = []
    page.route("**/api/strategies/Preset", lambda route: pending.append(route))
    response = page.request.get(f"{url}/api/strategies/Preset")
    page.locator("#apply-turn-strategy").click()
    playwright.expect(_option(page, "noChain")).to_be_disabled()
    playwright.expect(_option(page, "randomTouch")).to_be_disabled()
    playwright.expect(_option(page, "randomTime")).to_be_disabled()
    playwright.expect(_option(page, "firstBattleSet")).to_be_disabled()
    playwright.expect(_option(page, "noSpeedupSkill")).to_be_disabled()
    pending.pop().fulfill(response=response)
    playwright.expect(_option(page, "noChain")).to_be_enabled()
    playwright.expect(_option(page, "randomTouch")).to_be_enabled()
    playwright.expect(_option(page, "randomTime")).to_be_enabled()
    playwright.expect(_option(page, "firstBattleSet")).to_be_enabled()
    playwright.expect(_option(page, "noSpeedupSkill")).to_be_enabled()
    page.locator("#preset-json").fill("{")
    playwright.expect(_option(page, "noChain")).to_be_disabled()
    page.close()


def test_run_option_checkbox_keeps_keyboard_focus(tag_console):
    browser, url, _directory = tag_console
    page = browser.new_page()
    page.set_default_timeout(10000)
    page.goto(url)
    page.locator("#new-setting").click()
    page.locator("#preset-run-options summary").click()
    checkbox = _option(page, "noChain")
    checkbox.click()
    playwright.expect(checkbox).to_be_focused()
    page.keyboard.press("Space")
    playwright.expect(checkbox).not_to_be_checked()
    assert _config(page)["noChain"] is False
    page.close()


def test_incomplete_numeric_text_survives_unrelated_changes(tag_console):
    browser, url, _directory = tag_console
    page = browser.new_page()
    page.set_default_timeout(10000)
    page.goto(url)
    page.locator("#new-setting").click()
    page.locator("#preset-run-options summary").click()
    _option(page, "stuckRestart").check()
    interval = _option(page, "checkStuckInterval")
    interval.fill("")
    interval.press_sequentially("1e")
    interval.press("Tab")
    assert interval.evaluate("e => e.validity.badInput")
    _option(page, "noChain").check()
    assert interval.evaluate("e => e.validity.badInput")
    interval.click()
    interval.press("End")
    interval.press_sequentially("1")
    interval.press("Tab")
    playwright.expect(interval).to_have_value("10")
    assert _config(page)["checkStuckInterval"] == 10
    page.close()


@pytest.mark.parametrize("submit", ["enter", "button"])
def test_restoring_original_interval_without_blur_clears_error(tag_console, submit):
    browser, url, _directory = tag_console
    page = browser.new_page()
    page.set_default_timeout(10000)
    page.goto(url)
    page.locator("#new-setting").click()
    page.locator("#preset-name").fill("Corrected")
    config = {"server": "CH", "round1_turns": 1, "stuckRestart": True, "checkStuckInterval": 30}
    page.locator("#preset-json").fill(json.dumps(config))
    page.locator("#preset-run-options summary").click()
    interval = _option(page, "checkStuckInterval")
    interval.click()
    interval.press("Control+A")
    interval.press_sequentially("0")
    interval.press("Control+A")
    interval.press_sequentially("30")
    assert interval.evaluate("e => e.checkValidity()")
    if submit == "enter":
        interval.press("Enter")
    else:
        page.locator("#save-preset").click()
    playwright.expect(page.locator("#preset-dialog")).not_to_be_visible()
    assert page.request.get(f"{url}/api/settings/Corrected").json()["config"] == config
    page.close()


def test_run_options_unlock_after_save_failure_and_cancel_discards_draft(tag_console):
    browser, url, _directory = tag_console
    page = browser.new_page()
    page.set_default_timeout(10000)
    _seed(page, url)
    page.goto(url)
    page.locator("#edit-setting").click()
    page.locator("#preset-run-options summary").click()
    pending = []

    def hold_save(route):
        if route.request.method == "PUT":
            pending.append(route)
        else:
            route.continue_()

    page.route("**/api/settings/demo", hold_save)
    page.locator("#save-preset").click()
    playwright.expect(_option(page, "noChain")).to_be_disabled()
    pending.pop().fulfill(status=500, json={"error": {"message": "Save failed"}})
    playwright.expect(page.locator("#preset-error")).to_have_text("Save failed")
    playwright.expect(_option(page, "noChain")).to_be_enabled()
    _option(page, "stuckRestart").check()
    _option(page, "checkStuckInterval").fill("0")
    _option(page, "checkStuckInterval").press("Tab")
    page.locator("#cancel-preset").click()
    page.locator("#new-strategy").click()
    page.locator("#preset-name").fill("FreshStrategy")
    playwright.expect(page.locator("#preset-run-options")).not_to_be_visible()
    page.locator("#save-preset").click()
    playwright.expect(page.locator("#preset-dialog")).not_to_be_visible()
    assert page.request.get(f"{url}/api/strategies/FreshStrategy").ok
    page.close()


@pytest.mark.parametrize("invalid", ["30", None, {"toString": None}])
def test_malformed_interval_can_be_corrected_without_implicit_conversion(tag_console, invalid):
    browser, url, _directory = tag_console
    page = browser.new_page()
    page.set_default_timeout(10000)
    _entries, original = _seed(page, url)
    page.goto(url)
    page.locator("#edit-setting").click()
    config = {**original, "stuckRestart": True, "checkStuckInterval": invalid}
    page.locator("#preset-json").fill(json.dumps(config))
    page.locator("#preset-run-options summary").click()
    interval = _option(page, "checkStuckInterval")
    playwright.expect(interval).to_have_value("")
    page.locator("#save-preset").click()
    playwright.expect(page.locator("#preset-dialog")).to_be_visible()
    assert _config(page) == config
    assert page.request.get(f"{url}/api/settings/demo").json()["config"] == original
    interval.fill("30")
    interval.press("Tab")
    assert _config(page) == {**config, "checkStuckInterval": 30}
    page.locator("#save-preset").click()
    playwright.expect(page.locator("#preset-dialog")).not_to_be_visible()
    page.close()
