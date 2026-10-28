import json
import os

import pytest

playwright = pytest.importorskip("playwright.sync_api")
from tests.test_assist_tags_browser import tag_console
from tests.test_strategy_assignment_browser import _config, _seed

pytestmark = pytest.mark.skipif(not os.environ.get("BBCHANNEL_TEST_CHROMIUM"), reason="Set BBCHANNEL_TEST_CHROMIUM.")


@pytest.mark.parametrize("section,field,value", [
    ("preset-run-options", "randomTouch", True), ("preset-run-options", "noChain", True),
    ("preset-run-options", "firstBattleSet", True), ("preset-run-options", "noSpeedupSkill", True),
    ("preset-ap-options", "clearAP", True), ("preset-ap-options", "allowOtherApple", True),
    ("preset-run-options", "randomTime", 0.75), ("preset-run-options", "checkStuckInterval", 15.5),
    ("preset-operation-timing", "intervalBF", 0.4), ("preset-operation-timing", "intervalAF", 0.3),
    ("preset-operation-timing", "intervalBFchooseCard", 0.8), ("preset-drop-options", "dropStopNum", 0),
])
def test_run_option_edits_only_write_the_chosen_field_and_keep_numeric_source(tag_console, section, field, value):
    browser, url, directory = tag_console
    page = browser.new_page()
    _entries, original = _seed(page, url)
    original.update({"metadata": {"float": 1.0, "large": 9007199254740993}, "round1_turn0_skill": [1.0], "stuckRestart": True})
    path = directory / "data" / "settings" / "demo.json"
    path.write_text(json.dumps(original))
    page.goto(url)
    page.locator("#edit-setting").click()
    page.locator(f"#{section} summary").click()
    control = page.locator(f'[data-run-option="{field}"]')
    if isinstance(value, bool):
        control.set_checked(value)
    else:
        control.fill(str(value))
        control.press("Tab")
    draft = _config(page)
    assert draft == {**original, field: value}
    assert draft["metadata"]["large"] == 9007199254740993
    assert type(draft["metadata"]["float"]) is float
    assert type(draft["round1_turn0_skill"][0]) is float
    assert json.loads(path.read_text()) == original
    page.locator("#save-preset").click()
    playwright.expect(page.locator("#preset-dialog")).not_to_be_visible()
    saved = json.loads(path.read_text())
    assert saved == {**original, field: value}
    assert type(saved["metadata"]["float"]) is float
    assert type(saved["round1_turn0_skill"][0]) is float
    assert page.request.get(f"{url}/api/settings/demo/program").json()["summary"]["unsupported_action_count"] == 1
    page.close()


@pytest.mark.parametrize("section,field,source", [
    ("preset-run-options", "randomTouch", '{"server":"CH","randomTouch":true,"randomTouch":false}'),
    ("preset-run-options", "randomTouch", '{"server":"CH","randomTouch":true,"\\u0072andomTouch":false}'),
    ("preset-operation-timing", "intervalBF", '{"server":"CH","intervalBF":1.0,"intervalBF":2.0}'),
])
def test_ambiguous_run_options_are_disabled_until_raw_source_is_corrected(tag_console, section, field, source):
    browser, url, _directory = tag_console
    page = browser.new_page()
    _seed(page, url)
    page.goto(url)
    page.locator("#edit-setting").click()
    page.locator("#preset-json").fill(source)
    page.locator(f"#{section} summary").click()
    control = page.locator(f'[data-run-option="{field}"]')
    playwright.expect(control).to_be_disabled()
    assert page.locator("#preset-json").input_value() == source
    corrected = {"server": "CH", field: True if field == "randomTouch" else 0.4}
    page.locator("#preset-json").fill(json.dumps(corrected))
    playwright.expect(control).to_be_enabled()
    assert _config(page) == corrected
    page.close()
