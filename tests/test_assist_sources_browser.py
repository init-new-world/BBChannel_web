import json
import os

import pytest

playwright = pytest.importorskip("playwright.sync_api")
from tests.test_assist_tags_browser import tag_console
from tests.test_assist_options_browser import _option
from tests.test_strategy_assignment_browser import _config, _seed

pytestmark = pytest.mark.skipif(not os.environ.get("BBCHANNEL_TEST_CHROMIUM"), reason="Set BBCHANNEL_TEST_CHROMIUM.")
GRAND = "\u51a0\u4f4d\u52a9\u6218"
SERVANT = "\u4ec5\u4ece\u8005"
VALUES = {"assistMode": GRAND, "NPlevel": 2, "servantLevel": 90, "onlyFriendAssist": False,
          "allNotSkip": True, "fullEquip": False, "jbType": "\u4efb\u610f", "noGrandRefresh": False,
          "intervalAFswipeAssist": 0.5, "scrollLimit": 0.96}


def _legacy(page):
    config = _config(page)
    assert type(config["metadata"]["float"]) is float
    assert config["metadata"]["large"] == 9007199254740993
    assert type(config["round1_turn0_skill"][0]) is float
    assert type(config["round1_turn0_skill"][1][1]) is float


@pytest.mark.parametrize("width,locale", [(1440, "en-US"), (390, "zh-CN"), (320, "en-US")])
def test_assist_scalar_edits_keep_legacy_skill_types_big_integers_and_saved_program_semantics(tag_console, width, locale):
    browser, url, directory = tag_console
    page = browser.new_page(viewport={"width": width, "height": 900}, locale=locale)
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    _entries, original = _seed(page, url)
    original.update({"assistMode": GRAND, "metadata": {"float": 1.0, "large": 9007199254740993},
                     "round1_turn0_skill": [1.0, [1, 2.0]]})
    path = directory / "data" / "settings" / "demo.json"
    path.write_text(json.dumps(original))
    before = path.read_bytes()
    page.goto(url)
    page.locator("#edit-setting").click()
    page.locator("#preset-assist-options summary").click()
    _option(page, "assistMode").select_option(SERVANT)
    _legacy(page)
    _option(page, "assistMode").select_option(GRAND)
    _option(page, "NPlevel").select_option("3")
    _option(page, "jbType").select_option("NP50")
    for field in ("onlyFriendAssist", "fullEquip", "noGrandRefresh"):
        _option(page, field).check()
    _option(page, "allNotSkip").uncheck()
    for field, value in (("servantLevel", "120"), ("intervalAFswipeAssist", "0.75"), ("scrollLimit", "0.85")):
        _option(page, field).fill(value)
        _option(page, field).press("Tab")
    _legacy(page)
    expected = {**original, "NPlevel": 3, "jbType": "NP50", "onlyFriendAssist": True, "fullEquip": True,
                "noGrandRefresh": True, "allNotSkip": False, "servantLevel": 120, "intervalAFswipeAssist": 0.75, "scrollLimit": 0.85}
    assert _config(page) == expected
    assert path.read_bytes() == before
    page.locator("#preset-assist-options").scroll_into_view_if_needed()
    page.screenshot(path=str(directory / f"assist-source-{width}.png"))
    assert page.locator(".preset-form").evaluate("e => e.scrollWidth <= e.clientWidth")
    page.locator("#save-preset").click()
    playwright.expect(page.locator("#preset-dialog")).not_to_be_visible()
    saved = json.loads(path.read_text())
    assert saved == expected
    assert type(saved["metadata"]["float"]) is float
    assert saved["metadata"]["large"] == 9007199254740993
    assert type(saved["round1_turn0_skill"][0]) is float
    assert type(saved["round1_turn0_skill"][1][1]) is float
    assert page.request.get(f"{url}/api/settings/demo/program").json()["summary"]["unsupported_action_count"] == 2
    assert errors == []
    page.close()


@pytest.mark.parametrize("field", VALUES)
def test_duplicate_assist_keys_disable_only_the_corresponding_control_until_raw_correction(tag_console, field):
    browser, url, _directory = tag_console
    page = browser.new_page(locale="zh-CN")
    page.goto(url)
    page.locator("#new-setting").click()
    escaped = f"\\u{ord(field[0]):04x}" + field[1:]
    config = {"server": "CH", **VALUES, "metadata": {"float": 1.0, "large": 9007199254740993}}
    source = json.dumps(config)[:-1] + ',"' + escaped + '":' + json.dumps(VALUES[field]) + '}'
    page.locator("#preset-json").fill(source)
    page.locator("#preset-assist-options summary").click()
    playwright.expect(_option(page, field)).to_be_disabled()
    playwright.expect(_option(page, field)).to_have_attribute("title", "助战筛选字段含义不明确。")
    before = page.locator("#preset-json").input_value()
    _option(page, field).evaluate("e => e.dispatchEvent(new Event('change',{bubbles:true}))")
    assert page.locator("#preset-json").input_value() == before
    other = "onlyFriendAssist" if field == "NPlevel" else "NPlevel"
    playwright.expect(_option(page, other)).to_be_enabled()
    if other == "NPlevel":
        _option(page, other).select_option("4")
    else:
        _option(page, other).check()
    changed = page.locator("#preset-json").input_value()
    pairs = json.loads(changed, object_pairs_hook=list)
    assert [value for name, value in pairs if name == field] == [VALUES[field], VALUES[field]]
    assert '"' + escaped + '"' in changed
    assert type(_config(page)["metadata"]["float"]) is float
    assert _config(page)["metadata"]["large"] == 9007199254740993
    page.locator("#preset-json").fill(json.dumps(config))
    playwright.expect(_option(page, field)).to_be_enabled()
    assert _option(page, field).get_attribute("title") != "助战筛选字段含义不明确。"
    page.close()


def test_assist_source_edits_keep_partial_number_drafts_and_block_saving_them(tag_console):
    browser, url, directory = tag_console
    page = browser.new_page()
    _entries, original = _seed(page, url)
    original.update({"assistMode": GRAND, "metadata": {"float": 1.0, "large": 9007199254740993},
                     "round1_turn0_skill": [1.0, [1, 2.0]]})
    path = directory / "data" / "settings" / "demo.json"
    path.write_text(json.dumps(original))
    before = path.read_bytes()
    page.goto(url)
    page.locator("#edit-setting").click()
    page.locator("#preset-assist-options summary").click()
    wait = _option(page, "intervalAFswipeAssist")
    wait.fill("")
    wait.press_sequentially("1e")
    assert wait.evaluate("e => e.validity.badInput")
    _option(page, "NPlevel").select_option("3")
    _option(page, "onlyFriendAssist").check()
    assert wait.evaluate("e => e.validity.badInput")
    _legacy(page)
    page.locator("#save-preset").click()
    playwright.expect(page.locator("#preset-dialog")).to_be_visible()
    assert path.read_bytes() == before
    page.close()
