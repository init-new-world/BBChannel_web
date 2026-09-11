import json
import os

import pytest

playwright = pytest.importorskip("playwright.sync_api")
from tests.test_assist_tags_browser import tag_console

pytestmark = pytest.mark.skipif(
    not os.environ.get("BBCHANNEL_TEST_CHROMIUM"),
    reason="Set BBCHANNEL_TEST_CHROMIUM to a local Chromium executable.",
)


def _seed(page, url):
    spec = {"type": 1, "cards": ["1B", "2A"], "criticalStar": 0, "more_or_less": True}
    rule = {**{f"card{i}": spec for i in (1, 2, 3)}, "breakpoint": [False, False], "colorFirst": True}
    entries = [{"tag": "First", "strategy": {**rule, "extension": {"v": 1}}}, {"tag": "Fallback", "strategy": {**rule, "colorFirst": False}}]
    assert page.request.put(f"{url}/api/strategies/Preset", data={"entries": entries}).ok
    config = page.request.get(f"{url}/api/settings/demo").json()["config"]
    config.update({
        "round1_turns": 2, "round2_turns": 1, "round1_turn0_np": [2],
        "round1_turn1_strategy": [rule], "custom": {"untouched": [1, 2]},
    })
    assert page.request.put(f"{url}/api/settings/demo", data={"config": config, "overwrite": True}).ok
    return entries, config


def _config(page):
    return json.loads(page.locator("#preset-json").input_value())


@pytest.mark.parametrize("width,height", [(1440, 1000), (390, 844)])
def test_apply_and_clear_strategies_for_turns_without_changing_other_fields(tag_console, width, height):
    browser, url, directory = tag_console
    page = browser.new_page(viewport={"width": width, "height": height})
    page.set_default_timeout(10000)
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    entries, original = _seed(page, url)
    page.goto(url)
    page.locator("#edit-setting").click()
    target = page.locator("#preset-strategy-target")
    source = page.locator("#preset-strategy-source")
    playwright.expect(target).to_be_visible()
    assert target.locator("option").evaluate_all("options => options.map(option => option.value)") == [
        "round1_turn0_strategy", "round1_turn1_strategy", "round1_extraStrategy",
        "round2_turn0_strategy", "round2_extraStrategy",
    ]
    source.select_option("Preset")
    target.select_option("round1_turn0_strategy")
    page.locator("#apply-turn-strategy").click()
    playwright.expect(page.locator("#preset-turn-strategy-status")).to_have_text("2 strategies configured")
    copied = [entry["strategy"] for entry in entries]
    assert _config(page)["round1_turn0_strategy"] == copied
    assert page.request.get(f"{url}/api/settings/demo").json()["config"] == original
    target.select_option("round2_extraStrategy")
    page.locator("#apply-turn-strategy").click()
    playwright.expect(page.locator("#preset-turn-strategy-status")).to_have_text("2 strategies configured")
    target.select_option("round1_turn1_strategy")
    page.once("dialog", lambda dialog: dialog.accept())
    page.locator("#clear-turn-strategy").click()
    expected = {**original, "round1_turn0_strategy": copied, "round2_extraStrategy": copied}
    expected["round1_turn1_strategy"] = []
    assert _config(page) == expected
    playwright.expect(page.locator("#preset-turn-strategy-status")).to_have_text("No strategy configured")
    playwright.expect(page.locator("#clear-turn-strategy")).to_be_disabled()
    page.locator(".preset-form").evaluate("e => e.scrollTop = 0")
    page.screenshot(path=str(directory / f"strategy-assignment-{width}.png"))
    assert page.locator("#preset-dialog").evaluate("e => e.scrollWidth <= e.clientWidth")
    assert page.locator(".preset-form").evaluate("e => e.scrollWidth <= e.clientWidth")
    page.locator("#save-preset").click()
    playwright.expect(page.locator("#preset-dialog")).not_to_be_visible()
    assert page.request.get(f"{url}/api/settings/demo").json()["config"] == expected
    assert page.request.get(f"{url}/api/strategies/Preset").json()["entries"] == entries
    assert errors == []
    page.close()


def test_apply_rejects_stale_script_and_does_not_lock_next_editor(tag_console):
    browser, url, _directory = tag_console
    page = browser.new_page()
    page.set_default_timeout(10000)
    _entries, original = _seed(page, url)
    page.goto(url)
    page.locator("#edit-setting").click()
    page.locator("#preset-strategy-source").select_option("Preset")
    pending = []
    page.route("**/api/strategies/Preset", lambda route: pending.append(route))
    response = page.request.get(f"{url}/api/strategies/Preset")
    page.locator("#apply-turn-strategy").click()
    playwright.expect(page.locator("#save-preset")).to_be_disabled()
    modified = {**original, "custom": "new draft"}
    page.locator("#preset-json").fill(json.dumps(modified))
    assert len(pending) == 1
    pending.pop(0).fulfill(response=response)
    playwright.expect(page.locator("#preset-error")).to_contain_text("Script changed")
    playwright.expect(page.locator("#save-preset")).to_be_enabled()
    assert _config(page) == modified
    page.locator("#apply-turn-strategy").click()
    playwright.expect(page.locator("#save-preset")).to_be_disabled()
    page.locator("#cancel-preset").click()
    page.locator("#new-strategy").click()
    playwright.expect(page.locator("#preset-strategy-tag")).to_have_value("Entry 1")
    assert len(pending) == 1
    pending.pop(0).fulfill(response=response)
    playwright.expect(page.locator("#save-preset")).to_be_enabled()
    assert isinstance(_config(page), list)
    assert page.request.get(f"{url}/api/settings/demo").json()["config"] == original
    page.close()


def test_assignment_handles_inferred_turns_invalid_json_and_empty_presets(tag_console):
    browser, url, _directory = tag_console
    page = browser.new_page()
    page.set_default_timeout(10000)
    _seed(page, url)
    assert page.request.put(f"{url}/api/strategies/Empty", data={"entries": []}).ok
    page.goto(url)
    page.locator("#edit-setting").click()
    config = {"server": "CH", "round3_turn2_np": [1]}
    page.locator("#preset-json").fill(json.dumps(config))
    target = page.locator("#preset-strategy-target")
    assert target.locator("option").evaluate_all("options => options.map(option => option.value)") == [
        "round3_turn0_strategy", "round3_turn1_strategy", "round3_turn2_strategy", "round3_extraStrategy",
    ]
    page.locator("#preset-strategy-source").select_option("Empty")
    page.locator("#apply-turn-strategy").click()
    playwright.expect(page.locator("#preset-error")).to_contain_text("invalid or empty")
    assert _config(page) == config
    page.locator("#preset-json").fill("{")
    playwright.expect(page.locator("#apply-turn-strategy")).to_be_disabled()
    playwright.expect(target).to_be_disabled()
    page.locator("#preset-json").fill('{"server":"CH","round1_turns":0}')
    playwright.expect(page.locator("#apply-turn-strategy")).to_be_disabled()
    playwright.expect(target).to_be_disabled()
    page.close()


def test_cancel_replacement_and_clear_preserves_script_and_invalid_skill_draft(tag_console):
    browser, url, _directory = tag_console
    page = browser.new_page()
    page.set_default_timeout(10000)
    _entries, original = _seed(page, url)
    page.goto(url)
    page.locator("#edit-setting").click()
    page.locator("#preset-strategy-source").select_option("Preset")
    page.locator("#preset-strategy-target").select_option("round1_turn1_strategy")
    page.once("dialog", lambda dialog: dialog.dismiss())
    page.locator("#apply-turn-strategy").click()
    assert _config(page) == original
    page.once("dialog", lambda dialog: dialog.dismiss())
    page.locator("#clear-turn-strategy").click()
    assert _config(page) == original
    field = page.locator('[data-assist-skill-index="0"]')
    field.fill("11")
    field.press("Tab")
    page.locator("#preset-strategy-target").select_option("round1_turn0_strategy")
    page.locator("#apply-turn-strategy").click()
    playwright.expect(page.locator("#preset-turn-strategy-status")).to_have_text("2 strategies configured")
    playwright.expect(field).to_have_value("11")
    assert not field.evaluate("e => e.checkValidity()")
    page.locator("#save-preset").click()
    playwright.expect(page.locator("#preset-dialog")).to_be_visible()
    assert page.request.get(f"{url}/api/settings/demo").json()["config"] == original
    page.close()


def test_clearing_strategy_preserves_implicitly_declared_turns(tag_console):
    browser, url, _directory = tag_console
    page = browser.new_page()
    page.set_default_timeout(10000)
    entries, _original = _seed(page, url)
    page.goto(url)
    page.locator("#edit-setting").click()
    config = {"server": "CH", "round3_turn2_strategy": [entries[0]["strategy"]]}
    page.locator("#preset-json").fill(json.dumps(config))
    target = page.locator("#preset-strategy-target")
    target.select_option("round3_turn2_strategy")
    page.once("dialog", lambda dialog: dialog.accept())
    page.locator("#clear-turn-strategy").click()
    assert _config(page) == {"server": "CH", "round3_turn2_strategy": []}
    playwright.expect(target.locator("option")).to_have_count(4)
    playwright.expect(target).to_have_value("round3_turn2_strategy")
    playwright.expect(page.locator("#clear-turn-strategy")).to_be_disabled()
    page.close()


def test_strategy_assignment_is_disabled_while_script_save_is_pending(tag_console):
    browser, url, _directory = tag_console
    page = browser.new_page()
    page.set_default_timeout(10000)
    _seed(page, url)
    page.goto(url)
    page.locator("#edit-setting").click()
    pending = []

    def hold_save(route):
        if route.request.method == "PUT":
            pending.append(route)
        else:
            route.continue_()

    page.route("**/api/settings/demo", hold_save)
    page.locator("#save-preset").click()
    playwright.expect(page.locator("#save-preset")).to_be_disabled()
    playwright.expect(page.locator("#apply-turn-strategy")).to_be_disabled()
    playwright.expect(page.locator("#preset-strategy-target")).to_be_disabled()
    assert len(pending) == 1
    pending[0].fulfill(status=500, json={"error": {"message": "Save failed"}})
    playwright.expect(page.locator("#preset-error")).to_have_text("Save failed")
    playwright.expect(page.locator("#apply-turn-strategy")).to_be_enabled()
    playwright.expect(page.locator("#save-preset")).to_be_enabled()
    page.close()


def test_escape_discards_pending_strategy_application(tag_console):
    browser, url, _directory = tag_console
    page = browser.new_page()
    page.set_default_timeout(10000)
    _seed(page, url)
    page.goto(url)
    page.locator("#edit-setting").click()
    playwright.expect(page.locator("#preset-dialog")).to_be_visible()
    playwright.expect(page.locator("#preset-strategy-target")).to_have_value("round1_turn0_strategy")
    source = page.locator("#preset-json").input_value()
    pending = []
    page.route("**/api/strategies/Preset", lambda route: pending.append(route))
    response = page.request.get(f"{url}/api/strategies/Preset")
    page.locator("#apply-turn-strategy").click()
    playwright.expect(page.locator("#save-preset")).to_be_disabled()
    page.keyboard.press("Escape")
    playwright.expect(page.locator("#preset-dialog")).not_to_be_visible()
    assert len(pending) == 1
    pending[0].fulfill(response=response)
    playwright.expect(page.locator("#save-preset")).to_be_enabled()
    assert page.locator("#preset-json").input_value() == source
    page.close()


def test_excessive_turn_counts_leave_script_json_untouched(tag_console):
    browser, url, _directory = tag_console
    page = browser.new_page()
    page.set_default_timeout(10000)
    _seed(page, url)
    page.goto(url)
    page.locator("#edit-setting").click()
    source = '{"server":"CH","round1_turns":1000000000}'
    page.locator("#preset-json").fill(source)
    playwright.expect(page.locator("#preset-turn-strategy-status")).to_have_text("Turn list exceeds 1,000 entries.")
    playwright.expect(page.locator("#apply-turn-strategy")).to_be_disabled()
    assert page.locator("#preset-json").input_value() == source
    page.locator("#cancel-preset").click()
    playwright.expect(page.locator("#preset-dialog")).not_to_be_visible()
    page.close()
