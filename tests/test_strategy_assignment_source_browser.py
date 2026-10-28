import json
import os

import pytest

playwright = pytest.importorskip("playwright.sync_api")
from tests.test_assist_tags_browser import tag_console
from tests.test_strategy_assignment_browser import _config, _seed

pytestmark = pytest.mark.skipif(not os.environ.get("BBCHANNEL_TEST_CHROMIUM"), reason="Set BBCHANNEL_TEST_CHROMIUM.")


@pytest.mark.parametrize("action", ["apply", "clear"])
def test_strategy_assignment_preserves_typed_script_and_preset_extensions(tag_console, action):
    browser, url, directory = tag_console
    page = browser.new_page()
    entries, original = _seed(page, url)
    for index, entry in enumerate(entries):
        entry["strategy"]["extension"] = {"float": 2.0, "large": 9007199254740995 + index * 2}
    preset = directory / "data" / "strategy" / "Preset.json"
    preset.write_text(json.dumps(entries))
    original["metadata"] = {"float": 1.0, "large": 9007199254740993}
    original["round1_turn0_skill"] = [1.0]
    target = "round1_turn0_strategy" if action == "apply" else "round1_turn1_strategy"
    path = directory / "data" / "settings" / "demo.json"
    path.write_text(json.dumps(original))
    page.goto(url)
    page.locator("#edit-setting").click()
    page.locator("#preset-strategy-target").select_option(target)
    if action == "clear":
        page.once("dialog", lambda dialog: dialog.accept())
        page.locator("#clear-turn-strategy").click()
        expected = []
    else:
        page.locator("#apply-turn-strategy").click()
        playwright.expect(page.locator("#preset-turn-strategy-status")).to_have_text("2 strategies configured")
        expected = [entry["strategy"] for entry in entries]
    draft = _config(page)
    assert draft["metadata"]["large"] == 9007199254740993
    assert type(draft["metadata"]["float"]) is float
    assert type(draft["round1_turn0_skill"][0]) is float
    assert draft[target] == expected
    if action == "apply":
        assert type(draft[target][0]["extension"]["float"]) is float
    assert json.loads(path.read_text()) == original
    page.locator("#save-preset").click()
    playwright.expect(page.locator("#preset-dialog")).not_to_be_visible()
    saved = json.loads(path.read_text())
    assert saved == {**original, target: expected}
    assert type(saved["metadata"]["float"]) is float
    assert type(saved["round1_turn0_skill"][0]) is float
    if action == "apply":
        assert type(saved[target][0]["extension"]["float"]) is float
    assert json.loads(preset.read_text()) == entries
    page.close()


def test_duplicate_strategy_fields_disable_replacement_and_clear(tag_console):
    browser, url, _directory = tag_console
    page = browser.new_page()
    _seed(page, url)
    page.goto(url)
    page.locator("#edit-setting").click()
    source = '{"server":"CH","round1_turn0_strategy":[],"round1_turn0_strategy":[{}]}'
    page.locator("#preset-json").fill(source)
    playwright.expect(page.locator("#apply-turn-strategy")).to_be_disabled()
    playwright.expect(page.locator("#clear-turn-strategy")).to_be_disabled()
    assert page.locator("#preset-json").input_value() == source
    page.close()


def test_preset_response_for_a_changed_target_does_not_edit_the_previous_turn(tag_console):
    browser, url, _directory = tag_console
    page = browser.new_page()
    _seed(page, url)
    page.goto(url)
    page.locator("#edit-setting").click()
    response = page.request.get(f"{url}/api/strategies/Preset")
    pending = []
    page.route("**/api/strategies/Preset", lambda route: pending.append(route))
    before = page.locator("#preset-json").input_value()
    page.locator("#apply-turn-strategy").click()
    playwright.expect(page.locator("#preset-strategy-target")).to_be_disabled()
    page.locator("#preset-strategy-target").evaluate("e => {e.value='round2_extraStrategy'; e.dispatchEvent(new Event('change',{bubbles:true}));}")
    pending.pop().fulfill(response=response)
    playwright.expect(page.locator("#save-preset")).to_be_enabled()
    assert page.locator("#preset-json").input_value() == before
    page.close()
