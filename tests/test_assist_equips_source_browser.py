import json
import os

import pytest

playwright = pytest.importorskip("playwright.sync_api")
from tests.test_assist_tags_browser import tag_console
from tests.test_assist_equips_browser import _equips, _row
from tests.test_assist_sources_browser import _legacy
from tests.test_strategy_assignment_browser import _config, _seed

pytestmark = pytest.mark.skipif(not os.environ.get("BBCHANNEL_TEST_CHROMIUM"), reason="Set BBCHANNEL_TEST_CHROMIUM.")
MODE = "\u4ece\u8005\u793c\u88c5"


def _seed_equips(page, url, directory, value):
    _equips(directory)
    _entries, original = _seed(page, url)
    original.update({"assistMode": MODE, "assistEquip": value, "metadata": {"float": 1.0, "large": 9007199254740993},
                     "round1_turn0_skill": [1.0, [1, 2.0]]})
    path = directory / "data" / "settings" / "demo.json"
    path.write_text(json.dumps(original))
    return original, path


def _open(page, url):
    page.goto(url)
    page.locator("#edit-setting").click()
    page.locator("#preset-assist-equips summary").click()


@pytest.mark.parametrize("width,locale", [(1440, "en-US"), (390, "zh-CN"), (320, "en-US")])
def test_ce_add_remove_and_save_preserve_groups_other_source_and_unsupported_skill_types(tag_console, width, locale):
    browser, url, directory = tag_console
    page = browser.new_page(viewport={"width": width, "height": 900}, locale=locale)
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    original, path = _seed_equips(page, url, directory, [["First CE", "Missing CE"], ["First CE"], "", None])
    before = path.read_bytes()
    _open(page, url)
    playwright.expect(page.locator("#add-assist-equip")).to_be_enabled()
    page.locator("#preset-assist-equip-source").select_option("Second CE")
    page.locator("#add-assist-equip").click()
    _legacy(page)
    _row(page, "First CE").locator("button").click()
    _legacy(page)
    expected = {**original, "assistEquip": [["Missing CE"], [], "", None, "Second CE"]}
    assert _config(page) == expected
    playwright.expect(_row(page, "Missing CE").locator("button")).to_be_focused()
    page.wait_for_function("document.querySelector('[data-assist-equip-name=\"Second CE\"] img').naturalWidth === 237")
    page.locator("#preset-assist-equips").scroll_into_view_if_needed()
    page.screenshot(path=str(directory / f"assist-equip-source-{width}.png"))
    assert page.locator(".preset-form").evaluate("e => e.scrollWidth <= e.clientWidth")
    assert path.read_bytes() == before
    page.locator("#save-preset").click()
    playwright.expect(page.locator("#preset-dialog")).not_to_be_visible()
    saved = json.loads(path.read_text())
    assert saved == expected
    assert type(saved["metadata"]["float"]) is float
    assert saved["metadata"]["large"] == 9007199254740993
    assert type(saved["round1_turn0_skill"][0]) is float
    assert type(saved["round1_turn0_skill"][1][1]) is float
    assert page.request.get(f"{url}/api/settings/demo/plan").json()["assist"]["equip_names"] == ["Missing CE", "Second CE"]
    assert page.request.get(f"{url}/api/settings/demo/program").json()["summary"]["unsupported_action_count"] == 2
    assert errors == []
    page.close()


def test_ambiguous_ce_field_cannot_be_added_removed_or_cleared_and_other_fields_stay_editable(tag_console):
    browser, url, directory = tag_console
    page = browser.new_page(locale="zh-CN")
    original, _path = _seed_equips(page, url, directory, ["First CE"])
    _open(page, url)
    source = json.dumps(original)[:-1] + ',"assistE\\u0071uip":["Second CE"]}'
    page.locator("#preset-json").fill(source)
    playwright.expect(page.locator("#preset-assist-equip-status")).to_have_text("助战礼装字段含义不明确。")
    for control in ("#add-assist-equip", "#clear-assist-equips", "#refresh-assist-equips"):
        playwright.expect(page.locator(control)).to_be_disabled()
    dialogs = []
    page.on("dialog", lambda dialog: (dialogs.append(dialog.message), dialog.dismiss()))
    page.locator("#clear-assist-equips").evaluate("e => e.dispatchEvent(new Event('click',{bubbles:true}))")
    assert page.locator("#preset-json").input_value() == source
    assert dialogs == []
    page.locator("#preset-assist-options summary").click()
    page.locator('[data-assist-option="NPlevel"]').select_option("4")
    changed = page.locator("#preset-json").input_value()
    assert [value for name, value in json.loads(changed, object_pairs_hook=list) if name == "assistEquip"] == [["First CE"], ["Second CE"]]
    _legacy(page)
    page.locator("#preset-json").fill(json.dumps(original))
    playwright.expect(page.locator("#add-assist-equip")).to_be_enabled()
    page.locator("#add-assist-equip").click()
    _legacy(page)
    assert _config(page)["assistEquip"] == ["First CE", "Second CE"]
    page.close()


@pytest.mark.parametrize("invalid", [True, False], ids=["invalid-json", "escaped-duplicate"])
def test_delayed_ce_catalog_cannot_unlock_invalid_or_ambiguous_source(tag_console, invalid):
    browser, url, directory = tag_console
    page = browser.new_page()
    original, _path = _seed_equips(page, url, directory, ["First CE"])
    _open(page, url)
    playwright.expect(page.locator("#add-assist-equip")).to_be_enabled()
    pending = []
    page.route("**/api/equip-templates", lambda route: pending.append(route))
    page.locator("#refresh-assist-equips").click()
    playwright.expect(page.locator("#preset-assist-equip-status")).to_have_text("Loading CE catalog...")
    source = "{" if invalid else json.dumps(original)[:-1] + ',"assistE\\u0071uip":["Second CE"]}'
    page.locator("#preset-json").fill(source)
    with page.expect_response("**/api/equip-templates"):
        pending.pop().fulfill(json={"templates": [{"name": "Fresh CE", "location": "active"}]})
    page.wait_for_load_state("networkidle")
    playwright.expect(page.locator("#preset-assist-equip-status")).to_have_text(
        "Invalid script JSON." if invalid else "Ambiguous CE field."
    )
    for control in ("#add-assist-equip", "#clear-assist-equips", "#refresh-assist-equips"):
        playwright.expect(page.locator(control)).to_be_disabled()
    playwright.expect(page.locator("[data-assist-equip-name]")).to_have_count(0)
    assert page.locator("#preset-json").input_value() == source
    page.locator("#preset-json").fill(json.dumps(original))
    playwright.expect(page.locator("#add-assist-equip")).to_be_enabled()
    assert page.locator("#preset-assist-equip-source option").all_text_contents() == ["Fresh CE"]
    _legacy(page)
    page.close()


@pytest.mark.parametrize("value", [[1.0], {"future": ["First CE"], "keep": 1.0}, True])
def test_explicit_ce_clear_replaces_only_malformed_selected_values(tag_console, value):
    browser, url, directory = tag_console
    page = browser.new_page()
    original, _path = _seed_equips(page, url, directory, value)
    _open(page, url)
    playwright.expect(page.locator("#add-assist-equip")).to_be_disabled()
    before = page.locator("#preset-json").input_value()
    page.once("dialog", lambda dialog: dialog.dismiss())
    page.locator("#clear-assist-equips").click()
    assert page.locator("#preset-json").input_value() == before
    page.once("dialog", lambda dialog: dialog.accept())
    page.locator("#clear-assist-equips").click()
    assert _config(page) == {**original, "assistEquip": []}
    _legacy(page)
    playwright.expect(page.locator("#add-assist-equip")).to_be_enabled()
    page.locator("#add-assist-equip").click()
    _legacy(page)
    assert _config(page)["assistEquip"] == ["First CE"]
    page.close()


@pytest.mark.parametrize("operation", ["apply", "save"])
def test_ce_source_changes_stay_locked_during_pending_operations(tag_console, operation):
    browser, url, directory = tag_console
    page = browser.new_page()
    original, _path = _seed_equips(page, url, directory, ["First CE"])
    _open(page, url)
    playwright.expect(page.locator("#add-assist-equip")).to_be_enabled()
    pending = []
    if operation == "apply":
        response = page.request.get(f"{url}/api/strategies/Preset")
        page.route("**/api/strategies/Preset", lambda route: pending.append(route))
        page.locator("#apply-turn-strategy").click()
    else:
        page.route("**/api/settings/demo", lambda route: pending.append(route))
        page.locator("#save-preset").click()
    playwright.expect(page.locator("#add-assist-equip")).to_be_disabled()
    before = page.locator("#preset-json").input_value()
    page.locator("#add-assist-equip").evaluate("e => e.dispatchEvent(new Event('click',{bubbles:true}))")
    _row(page, "First CE").locator("button").evaluate("e => e.dispatchEvent(new Event('click',{bubbles:true}))")
    assert page.locator("#preset-json").input_value() == before
    if operation == "apply":
        pending.pop().fulfill(response=response)
    else:
        pending.pop().fulfill(status=500, json={"error": {"message": "Save failed"}})
    playwright.expect(page.locator("#add-assist-equip")).to_be_enabled()
    assert _config(page)["assistEquip"] == original["assistEquip"]
    _legacy(page)
    page.close()
