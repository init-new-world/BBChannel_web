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


def _masters(directory):
    (directory / "data" / "master_info.json").write_text(json.dumps({
        "Default outfit": {"SN": 0}, "Combat outfit": {"SN": 7},
        "Travel outfit with a long descriptive catalog name": {"SN": "008"},
    }))


@pytest.mark.parametrize("width,height", [(1440, 1000), (390, 844)])
def test_master_outfit_changes_are_draft_only_and_update_plan(tag_console, width, height):
    browser, url, directory = tag_console
    _masters(directory)
    page = browser.new_page(viewport={"width": width, "height": height})
    page.set_default_timeout(10000)
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    _entries, original = _seed(page, url)
    original.update({"master_equip": "7", "master_sex": 1})
    assert page.request.put(f"{url}/api/settings/demo", data={"config": original, "overwrite": True}).ok
    page.goto(url)
    page.locator("#edit-setting").click()
    page.locator("#preset-team summary").click()
    outfit = page.locator("#preset-master-equip")
    playwright.expect(outfit).to_be_enabled()
    playwright.expect(outfit).to_have_value("7")
    assert _config(page) == original
    outfit.focus()
    outfit.select_option("0")
    playwright.expect(outfit).to_be_focused()
    assert _config(page)["master_equip"] == 0
    outfit.select_option("008")
    expected = {**original, "master_equip": "008"}
    assert _config(page) == expected
    assert page.request.get(f"{url}/api/settings/demo").json()["config"] == original
    playwright.expect(outfit).to_have_attribute("title", "Travel outfit with a long descriptive catalog name")
    page.locator("#preset-team").scroll_into_view_if_needed()
    page.screenshot(path=str(directory / f"master-editor-{width}.png"))
    assert page.locator(".preset-form").evaluate("e => e.scrollWidth <= e.clientWidth")
    page.locator("#save-preset").click()
    playwright.expect(page.locator("#preset-dialog")).not_to_be_visible()
    assert page.request.get(f"{url}/api/settings/demo").json()["config"] == expected
    master = page.request.get(f"{url}/api/settings/demo/plan").json()["master"]
    assert master == {"equip": "008", "name": "Travel outfit with a long descriptive catalog name", "sex": 1}
    assert errors == []
    page.close()


@pytest.mark.parametrize("value", [None, "", "unknown", {"future": 1}, False])
def test_unknown_master_value_is_preserved_and_native_none_clears_only_outfit(tag_console, value):
    browser, url, directory = tag_console
    _masters(directory)
    page = browser.new_page()
    page.goto(url)
    page.locator("#new-setting").click()
    raw = {"server": "CH", "master_equip": value, "master_sex": 1, "custom": [1, 2]}
    page.locator("#preset-json").fill(json.dumps(raw))
    page.locator("#preset-team summary").click()
    outfit = page.locator("#preset-master-equip")
    playwright.expect(outfit).to_be_enabled()
    playwright.expect(outfit.locator("option:checked")).to_contain_text("current")
    assert _config(page) == raw
    outfit.focus()
    outfit.press("Space")
    outfit.press("Home")
    outfit.press("Enter")
    expected = {**raw}
    del expected["master_equip"]
    assert _config(page) == expected
    page.close()


def test_master_catalog_can_retry_independently_of_servant_catalog_and_server(tag_console):
    browser, url, directory = tag_console
    _masters(directory)
    page = browser.new_page()
    page.route("**/api/masters", lambda route: route.fulfill(status=503, json={"error": {"message": "Outfit catalog offline"}}))
    page.goto(url)
    page.locator("#new-setting").click()
    page.locator("#preset-team summary").click()
    playwright.expect(page.locator("#preset-master-status")).to_contain_text("Outfit catalog offline")
    playwright.expect(page.locator("#preset-master-equip")).to_be_disabled()
    playwright.expect(page.locator('[data-team-slot="0"]')).to_be_enabled()
    playwright.expect(page.locator("#save-preset")).to_be_enabled()
    page.unroute("**/api/masters")
    retry = page.locator("#retry-master-catalog")
    retry.focus()
    retry.press("Enter")
    outfit = page.locator("#preset-master-equip")
    playwright.expect(outfit).to_be_enabled()
    playwright.expect(outfit).to_be_focused()
    page.locator("#preset-json").fill(json.dumps({"server": "unsupported", "custom": 2}))
    outfit.select_option("7")
    assert _config(page) == {"server": "unsupported", "custom": 2, "master_equip": 7}
    page.locator("#preset-json").fill("{")
    playwright.expect(outfit).to_be_disabled()
    page.close()


def test_empty_master_catalog_still_allows_clearing_an_existing_outfit(tag_console):
    browser, url, _directory = tag_console
    page = browser.new_page()
    page.goto(url)
    page.locator("#new-setting").click()
    page.locator("#preset-json").fill(json.dumps({"server": "CH", "master_equip": 99}))
    page.locator("#preset-team summary").click()
    outfit = page.locator("#preset-master-equip")
    playwright.expect(outfit).to_be_enabled()
    playwright.expect(page.locator("#preset-master-status")).to_contain_text("No outfits")
    outfit.select_option("")
    assert _config(page) == {"server": "CH"}
    page.close()


def test_stale_master_response_does_not_replace_new_editor_or_invalid_drafts(tag_console):
    browser, url, _directory = tag_console
    page = browser.new_page()
    pending = []
    page.route("**/api/masters", lambda route: pending.append(route))
    page.goto(url)
    page.locator("#new-setting").click()
    playwright.expect(page.locator("#preset-master-status")).to_contain_text("Loading")
    page.locator("#cancel-preset").click()
    page.locator("#new-setting").click()
    playwright.expect(page.locator("#preset-master-status")).to_contain_text("Loading")
    skill = page.locator('[data-assist-skill-index="0"]')
    skill.fill("11")
    skill.press("Tab")
    pending.pop(0).fulfill(json={"masters": [{"name": "Stale", "sn": 1}]})
    pending.pop(0).fulfill(json={"masters": [{"name": "Fresh", "sn": "02"}]})
    outfit = page.locator("#preset-master-equip")
    playwright.expect(outfit).to_be_enabled()
    assert outfit.locator("option").all_text_contents() == ["None", "Fresh"]
    page.locator("#preset-team summary").click()
    outfit.select_option("02")
    playwright.expect(skill).to_have_value("11")
    assert _config(page) == {"server": "CH", "round1_turns": 0, "master_equip": "02"}
    page.close()


def test_master_controls_lock_during_preset_load_and_save(tag_console):
    browser, url, directory = tag_console
    _masters(directory)
    page = browser.new_page()
    _seed(page, url)
    page.goto(url)
    page.locator("#edit-setting").click()
    pending = []
    page.route("**/api/strategies/Preset", lambda route: pending.append(route))
    response = page.request.get(f"{url}/api/strategies/Preset")
    page.locator("#apply-turn-strategy").click()
    outfit = page.locator("#preset-master-equip")
    playwright.expect(outfit).to_be_disabled()
    pending.pop().fulfill(response=response)
    playwright.expect(outfit).to_be_enabled()
    page.route("**/api/settings/demo", lambda route: pending.append(route))
    page.locator("#save-preset").click()
    playwright.expect(outfit).to_be_disabled()
    pending.pop().fulfill(status=500, json={"error": {"message": "Save failed"}})
    playwright.expect(outfit).to_be_enabled()
    page.close()


@pytest.mark.parametrize("name,sn,current", [("", 7, 7), ("A invalid", False, "False"), ("A invalid", None, "None")])
def test_malformed_master_metadata_cannot_be_skipped_in_favor_of_duplicate_id(tag_console, name, sn, current):
    browser, url, directory = tag_console
    (directory / "data" / "master_info.json").write_text(json.dumps({
        name: {"SN": sn}, "Z misleading outfit": {"SN": current},
    }))
    page = browser.new_page()
    page.goto(url)
    page.locator("#new-setting").click()
    raw = {"server": "CH", "master_equip": current, "custom": 1}
    page.locator("#preset-json").fill(json.dumps(raw))
    page.locator("#preset-team summary").click()
    playwright.expect(page.locator("#preset-master-status")).to_have_text("Invalid master outfit catalog.")
    playwright.expect(page.locator("#preset-master-equip")).to_be_disabled()
    playwright.expect(page.locator('[data-team-slot="0"]')).to_be_enabled()
    assert _config(page) == raw
    _masters(directory)
    page.locator("#retry-master-catalog").click()
    playwright.expect(page.locator("#preset-master-equip")).to_be_enabled()
    assert _config(page) == raw
    page.close()


def test_duplicate_master_ids_follow_backend_first_match_order(tag_console):
    browser, url, directory = tag_console
    (directory / "data" / "master_info.json").write_text(json.dumps({
        "A first outfit": {"SN": 7}, "Z duplicate": {"SN": "7"},
    }))
    page = browser.new_page()
    page.goto(url)
    page.locator("#new-setting").click()
    page.locator("#preset-name").fill("DuplicateId")
    raw = {"server": "CH", "round1_turns": 1, "master_equip": "7"}
    page.locator("#preset-json").fill(json.dumps(raw))
    page.locator("#preset-team summary").click()
    outfit = page.locator("#preset-master-equip")
    playwright.expect(outfit).to_be_enabled()
    assert outfit.locator("option").all_text_contents() == ["None", "A first outfit"]
    assert _config(page) == raw
    page.locator("#save-preset").click()
    playwright.expect(page.locator("#preset-dialog")).not_to_be_visible()
    assert page.request.get(f"{url}/api/settings/DuplicateId/plan").json()["master"]["name"] == "A first outfit"
    page.close()
