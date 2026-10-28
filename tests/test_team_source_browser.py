import json
import os

import pytest

playwright = pytest.importorskip("playwright.sync_api")
from tests.test_assist_tags_browser import tag_console
from tests.test_master_editor_browser import _masters
from tests.test_strategy_assignment_browser import _config, _seed
from tests.test_team_editor_browser import _catalog

pytestmark = pytest.mark.skipif(not os.environ.get("BBCHANNEL_TEST_CHROMIUM"), reason="Set BBCHANNEL_TEST_CHROMIUM.")


@pytest.mark.parametrize("action", ["servant", "clear-servant", "assist", "clear-assist", "master", "clear-master", "gender", "server", "used"])
def test_team_edits_preserve_unrelated_typed_source_and_skill_meaning(tag_console, action):
    browser, url, directory = tag_console
    _catalog(directory)
    _masters(directory)
    (directory / "data" / "servant_info_JP.json").write_text(json.dumps({"Support": {"SN": "314"}}))
    page = browser.new_page()
    _entries, original = _seed(page, url)
    original.update({"metadata": {"float": 1.0, "large": 9007199254740993}, "round1_turn0_skill": [1.0],
                     "servant_0_name": "Support", "servant_4_name": "Support", "master_equip": 7, "master_sex": 1})
    path = directory / "data" / "settings" / "demo.json"
    path.write_text(json.dumps(original))
    page.goto(url)
    page.locator("#edit-setting").click()
    page.locator("#preset-team summary").click()
    expected = dict(original)
    if action in {"servant", "clear-servant"}:
        value = "Support" if action == "servant" else ""
        page.locator('[data-team-slot="1"]' if action == "servant" else '[data-team-slot="0"]').select_option(value)
        expected["servant_1_name" if action == "servant" else "servant_0_name"] = value
    elif action in {"assist", "clear-assist"}:
        page.locator("#preset-assist-slot").select_option("4" if action == "assist" else "")
        if action == "assist":
            expected["assistIdx"] = 4
        else:
            del expected["assistIdx"]
    elif action in {"master", "clear-master"}:
        control = page.locator("#preset-master-equip")
        playwright.expect(control).to_be_enabled()
        control.select_option("008" if action == "master" else "")
        if action == "master":
            expected["master_equip"] = "008"
        else:
            del expected["master_equip"]
    elif action == "gender":
        page.locator("#preset-master-sex").select_option("0")
        expected["master_sex"] = 0
    elif action == "server":
        page.locator("#preset-server").select_option("JP")
        expected["server"] = "JP"
    else:
        page.locator('[data-team-used="3"]').check()
        expected["usedServant"] = [0, 1, 2, 3]
    assert _config(page) == expected
    assert type(_config(page)["metadata"]["float"]) is float
    assert type(_config(page)["round1_turn0_skill"][0]) is float
    assert json.loads(path.read_text()) == original
    page.locator("#save-preset").click()
    playwright.expect(page.locator("#preset-dialog")).not_to_be_visible()
    saved = json.loads(path.read_text())
    assert saved == expected
    assert type(saved["metadata"]["float"]) is float
    assert type(saved["round1_turn0_skill"][0]) is float
    page.close()


def test_float_verification_slots_match_backend_and_survive_other_slot_edits(tag_console):
    browser, url, directory = tag_console
    page = browser.new_page()
    _entries, original = _seed(page, url)
    original.update({"servant_0_name": "Support", "usedServant": [0.0, 1, 2, 9007199254740993, {"future": 1.0}]})
    path = directory / "data" / "settings" / "demo.json"
    path.write_text(json.dumps(original))
    page.goto(url)
    page.locator("#edit-setting").click()
    page.locator("#preset-team summary").click()
    slot = page.locator('[data-team-used="0"]')
    playwright.expect(slot).not_to_be_checked()
    playwright.expect(page.locator("#preset-used-status")).to_have_text("Unrecognized entries retained.")
    page.locator('[data-team-used="1"]').uncheck()
    slot.check()
    expected = [0.0, 2, 9007199254740993, {"future": 1.0}, 0]
    assert _config(page)["usedServant"] == expected
    assert type(_config(page)["usedServant"][0]) is float
    page.locator("#save-preset").click()
    playwright.expect(page.locator("#preset-dialog")).not_to_be_visible()
    assert type(json.loads(path.read_text())["usedServant"][0]) is float
    plan = page.request.get(f"{url}/api/settings/demo/plan").json()
    assert plan["servants"][0]["used"] is True
    page.close()


@pytest.mark.parametrize("field,selector,raw,corrected", [
    ("server", "#preset-server", '"server":"CH","ser\\u0076er":"JP"', "CH"),
    ("master_sex", "#preset-master-sex", '"master_sex":0,"master_sex":1', 0),
    ("assistIdx", "#preset-assist-slot", '"assistIdx":0,"assistIdx":3', 3),
    ("servant_0_name", '[data-team-slot="0"]', '"servant_0_name":"Support","servant_0_name":"Unknown"', "Support"),
    ("usedServant", '[data-team-used="0"]', '"usedServant":[],"usedServant":[1]', [0]),
])
def test_duplicate_team_fields_disable_the_affected_controls_until_source_is_corrected(tag_console, field, selector, raw, corrected):
    browser, url, _directory = tag_console
    page = browser.new_page()
    _seed(page, url)
    page.goto(url)
    page.locator("#edit-setting").click()
    page.locator("#preset-team summary").click()
    source = '{' + ('' if field == "server" else '"server":"CH",') + raw + '}'
    page.locator("#preset-json").fill(source)
    control = page.locator(selector)
    playwright.expect(control).to_be_disabled()
    assert page.locator("#preset-json").input_value() == source
    fixed = {"server": "CH", field: corrected}
    page.locator("#preset-json").fill(json.dumps(fixed))
    playwright.expect(control).to_be_enabled()
    assert _config(page) == fixed
    page.close()
