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


def _catalog(directory):
    (directory / "data" / "servant_info_CH.json").write_text(json.dumps({
        "Support": {"SN": "314", "class": "Caster", "other_name": ["Support alias"]},
        "Attacker": {"SN": "001", "class": "Saber", "NPcolor": "B"},
        "Long servant name with enough words to fill the mobile selector": {"SN": "002"},
    }))


def _slot(page, index):
    return page.locator(f'[data-team-slot="{index}"]')


def _verify_slot(page, index):
    return page.locator(f'[data-team-used="{index}"]')


@pytest.mark.parametrize("width,height", [(1440, 1000), (390, 844)])
def test_team_verification_defaults_and_saved_plan(tag_console, width, height):
    browser, url, directory = tag_console
    page = browser.new_page(viewport={"width": width, "height": height})
    original = {"server": "CH", "round1_turns": 0,
                "servant_0_name": "Support", "servant_3_name": "Support"}
    assert page.request.put(f"{url}/api/settings/demo", data={"config": original, "overwrite": True}).ok
    page.goto(url)
    page.locator("#edit-setting").click()
    page.locator("#preset-team summary").click()
    for index in range(6):
        assert _verify_slot(page, index).is_checked() == (index < 3)
    assert _config(page) == original
    _verify_slot(page, 3).check()
    _verify_slot(page, 1).uncheck()
    expected = {**original, "usedServant": [0, 2, 3]}
    assert _config(page) == expected
    page.locator("#preset-team").scroll_into_view_if_needed()
    page.screenshot(path=str(directory / f"team-verification-{width}.png"))
    assert page.locator(".preset-form").evaluate("e => e.scrollWidth <= e.clientWidth")
    assert _verify_slot(page, 5).evaluate("e => e.getBoundingClientRect().right <= e.closest('fieldset').getBoundingClientRect().right")
    page.locator("#save-preset").click()
    playwright.expect(page.locator("#preset-dialog")).not_to_be_visible()
    assert page.request.get(f"{url}/api/settings/demo").json()["config"] == expected
    servants = page.request.get(f"{url}/api/settings/demo/plan").json()["servants"]
    assert servants[0]["used"] is True
    assert servants[1]["used"] is False
    assert servants[3]["used"] is True
    page.close()


def test_team_verification_preserves_other_array_entries_and_works_without_catalog(tag_console):
    browser, url, _directory = tag_console
    page = browser.new_page()
    page.route("**/api/servants?*", lambda route: route.fulfill(status=503, json={"error": {"message": "Catalog offline"}}))
    page.goto(url)
    page.locator("#new-setting").click()
    raw = {"server": "CH", "usedServant": [3, 0, 3, "legacy", 7, False]}
    page.locator("#preset-json").fill(json.dumps(raw))
    page.locator("#preset-team summary").click()
    playwright.expect(page.locator("#preset-team-status")).to_contain_text("Catalog offline")
    playwright.expect(_verify_slot(page, 3)).to_be_enabled()
    assert _verify_slot(page, 3).is_checked()
    assert not _verify_slot(page, 1).is_checked()
    assert _config(page) == raw
    _verify_slot(page, 3).uncheck()
    _verify_slot(page, 5).check()
    assert _config(page) == {**raw, "usedServant": [0, "legacy", 7, False, 5]}
    page.close()


def test_team_verification_invalid_root_is_preserved_until_json_is_fixed(tag_console):
    browser, url, _directory = tag_console
    page = browser.new_page()
    page.goto(url)
    page.locator("#new-setting").click()
    raw = {"server": "CH", "usedServant": {"future": [1, 2]}}
    page.locator("#preset-json").fill(json.dumps(raw))
    page.locator("#preset-team summary").click()
    playwright.expect(page.locator("#preset-used-status")).to_have_text("Invalid usedServant value.")
    playwright.expect(_verify_slot(page, 0)).to_be_disabled()
    _slot(page, 0).select_option("Support")
    assert _config(page) == {**raw, "servant_0_name": "Support"}
    page.locator("#preset-json").fill(json.dumps({"server": "CH", "usedServant": [0, 5]}))
    playwright.expect(_verify_slot(page, 5)).to_be_enabled()
    assert _verify_slot(page, 5).is_checked()
    page.close()


@pytest.mark.parametrize("width,height", [(1440, 1000), (390, 844)])
def test_team_changes_are_draft_only_and_update_saved_plan(tag_console, width, height):
    browser, url, directory = tag_console
    _catalog(directory)
    page = browser.new_page(viewport={"width": width, "height": height})
    page.set_default_timeout(10000)
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    _entries, original = _seed(page, url)
    original.update({"servant_1_name": "Support alias", "usedServant": [0, 1, 3]})
    assert page.request.put(f"{url}/api/settings/demo", data={"config": original, "overwrite": True}).ok
    page.goto(url)
    page.locator("#edit-setting").click()
    page.locator("#preset-team summary").click()
    playwright.expect(_slot(page, 0)).to_be_enabled()
    assert _config(page) == original
    playwright.expect(_slot(page, 1)).to_have_value("Support alias")
    playwright.expect(page.locator("#preset-assist-slot")).to_have_value("3")
    for index in range(6):
        _slot(page, index).select_option("Attacker" if index < 3 else "Support")
    _slot(page, 4).select_option("")
    long_name = "Long servant name with enough words to fill the mobile selector"
    _slot(page, 5).select_option(long_name)
    page.locator("#preset-assist-slot").select_option("5")
    expected = {**original, "assistIdx": 5, **{f"servant_{i}_name": "Attacker" if i < 3 else "Support" for i in range(6)}}
    expected.update({"servant_4_name": "", "servant_5_name": long_name})
    assert _config(page) == expected
    assert page.request.get(f"{url}/api/settings/demo").json()["config"] == original
    page.locator("#preset-team").scroll_into_view_if_needed()
    page.screenshot(path=str(directory / f"team-editor-{width}.png"))
    assert page.locator(".preset-form").evaluate("e => e.scrollWidth <= e.clientWidth")
    assert _slot(page, 5).evaluate("e => e.getBoundingClientRect().right <= e.closest('fieldset').getBoundingClientRect().right")
    playwright.expect(_slot(page, 5)).to_have_attribute("title", long_name)
    assert _slot(page, 5).evaluate("e => parseFloat(getComputedStyle(e).paddingRight) >= 24")
    page.locator("#save-preset").click()
    playwright.expect(page.locator("#preset-dialog")).not_to_be_visible()
    assert page.request.get(f"{url}/api/settings/demo").json()["config"] == expected
    plan = page.request.get(f"{url}/api/settings/demo/plan").json()
    assert plan["assist"]["slot"] == 5
    assert plan["assist"]["servant_name"] == long_name
    assert plan["servants"][0]["canonical_name"] == "Attacker"
    assert errors == []
    page.close()


def test_team_preserves_unrecognized_values_until_explicitly_replaced(tag_console):
    browser, url, directory = tag_console
    _catalog(directory)
    page = browser.new_page()
    page.goto(url)
    page.locator("#new-setting").click()
    raw = {"server": "ch", "servant_0_name": "Unknown", "servant_1_name": {"future": True},
           "servant_2_name": None, "assistIdx": "3", "custom": [1, 2]}
    page.locator("#preset-json").fill(json.dumps(raw))
    page.locator("#preset-team summary").click()
    playwright.expect(_slot(page, 0)).to_be_enabled()
    playwright.expect(_slot(page, 0)).to_have_value("Unknown")
    playwright.expect(_slot(page, 1).locator("option:checked")).to_have_text("Invalid name")
    playwright.expect(page.locator("#preset-assist-slot option:checked")).to_have_text("Invalid slot")
    assert _config(page) == raw
    _slot(page, 3).select_option("Support")
    assert _config(page) == {**raw, "servant_3_name": "Support"}
    _slot(page, 1).select_option("Attacker")
    page.locator("#preset-assist-slot").select_option("0")
    page.locator("#preset-assist-slot").select_option("")
    expected = {**raw, "servant_1_name": "Attacker", "servant_3_name": "Support"}
    del expected["assistIdx"]
    assert _config(page) == expected
    page.locator("#cancel-preset").click()
    page.locator("#new-strategy").click()
    playwright.expect(page.locator("#preset-team")).to_be_hidden()
    page.close()


def test_catalog_failure_can_retry_without_blocking_unrelated_changes(tag_console):
    browser, url, directory = tag_console
    _catalog(directory)
    page = browser.new_page()
    page.route("**/api/servants?*", lambda route: route.fulfill(status=503, json={"error": {"message": "Catalog unavailable"}}))
    page.goto(url)
    page.locator("#edit-setting").click()
    page.locator("#preset-team summary").click()
    playwright.expect(page.locator("#preset-team-status")).to_contain_text("Catalog unavailable")
    playwright.expect(_slot(page, 3)).to_have_value("Support")
    playwright.expect(_slot(page, 3)).to_be_disabled()
    playwright.expect(page.locator("#save-preset")).to_be_enabled()
    page.locator("#preset-assist-slot").select_option("1")
    assert _config(page)["assistIdx"] == 1
    page.unroute("**/api/servants?*")
    page.locator("#retry-team-catalog").click()
    playwright.expect(_slot(page, 0)).to_be_enabled()
    _slot(page, 0).select_option("Attacker")
    assert _config(page)["servant_0_name"] == "Attacker"
    page.locator("#preset-json").fill("{")
    playwright.expect(_slot(page, 0)).to_be_disabled()
    playwright.expect(page.locator("#preset-assist-slot")).to_be_disabled()
    page.locator("#preset-json").fill(json.dumps({"server": "unsupported"}))
    playwright.expect(page.locator("#preset-team-status")).to_contain_text("Unsupported server")
    playwright.expect(_slot(page, 0)).to_be_disabled()
    page.close()


def test_outdated_catalogs_cannot_replace_new_server_or_editor(tag_console):
    browser, url, _directory = tag_console
    page = browser.new_page()
    pending = []
    page.route("**/api/servants?*", lambda route: pending.append(route))
    page.goto(url)
    page.locator("#new-setting").click()
    page.locator("#preset-team summary").click()
    playwright.expect(page.locator("#preset-team-status")).to_contain_text("Loading")
    page.locator("#preset-json").fill(json.dumps({"server": "JP"}))
    playwright.expect(page.locator("#preset-team-status")).to_contain_text("JP")
    page.locator("#preset-json").fill(json.dumps({"server": "CH", "custom": "current"}))
    playwright.expect(page.locator("#preset-team-status")).to_contain_text("CH")
    assert len(pending) == 3
    pending.pop(0).fulfill(json={"server": "CH", "servants": [{"name": "Old"}]})
    pending.pop(0).fulfill(json={"server": "JP", "servants": [{"name": "Wrong"}]})
    playwright.expect(_slot(page, 0)).to_be_disabled()
    pending.pop(0).fulfill(json={"server": "CH", "servants": [{"name": "Current"}]})
    playwright.expect(_slot(page, 0)).to_be_enabled()
    assert _slot(page, 0).locator("option").all_text_contents() == ["None", "Current"]
    assert _config(page) == {"server": "CH", "custom": "current"}
    page.locator("#preset-json").fill(json.dumps({"server": "JP"}))
    playwright.expect(_slot(page, 0)).to_be_disabled()
    page.locator("#cancel-preset").click()
    page.locator("#new-setting").click()
    playwright.expect(page.locator("#preset-team-status")).to_contain_text("CH")
    assert len(pending) == 2
    pending.pop(0).fulfill(json={"server": "JP", "servants": [{"name": "Closed"}]})
    pending.pop(0).fulfill(json={"server": "CH", "servants": [{"name": "Fresh"}]})
    playwright.expect(_slot(page, 0)).to_be_enabled()
    assert _slot(page, 0).locator("option").all_text_contents() == ["None", "Fresh"]
    assert _config(page) == {"server": "CH", "round1_turns": 0}
    page.close()


def test_team_locks_during_preset_load_and_save_and_keeps_focus(tag_console):
    browser, url, directory = tag_console
    _catalog(directory)
    page = browser.new_page()
    _seed(page, url)
    page.goto(url)
    page.locator("#edit-setting").click()
    page.locator("#preset-team summary").click()
    playwright.expect(_slot(page, 0)).to_be_enabled()
    _slot(page, 0).focus()
    _slot(page, 0).select_option("Attacker")
    playwright.expect(_slot(page, 0)).to_be_focused()
    pending = []
    page.route("**/api/strategies/Preset", lambda route: pending.append(route))
    response = page.request.get(f"{url}/api/strategies/Preset")
    page.locator("#apply-turn-strategy").click()
    playwright.expect(_slot(page, 0)).to_be_disabled()
    playwright.expect(page.locator("#preset-assist-slot")).to_be_disabled()
    playwright.expect(_verify_slot(page, 0)).to_be_disabled()
    pending.pop(0).fulfill(response=response)
    playwright.expect(_slot(page, 0)).to_be_enabled()
    playwright.expect(_verify_slot(page, 0)).to_be_enabled()
    page.route("**/api/settings/demo", lambda route: pending.append(route))
    page.locator("#save-preset").click()
    playwright.expect(_slot(page, 0)).to_be_disabled()
    playwright.expect(_verify_slot(page, 0)).to_be_disabled()
    pending.pop(0).fulfill(status=500, json={"error": {"message": "Save failed"}})
    playwright.expect(_slot(page, 0)).to_be_enabled()
    playwright.expect(_verify_slot(page, 0)).to_be_enabled()
    page.close()


def test_team_load_and_changes_preserve_invalid_skill_and_interval_drafts(tag_console):
    browser, url, _directory = tag_console
    page = browser.new_page()
    pending = []
    page.route("**/api/servants?*", lambda route: pending.append(route))
    page.goto(url)
    page.locator("#new-setting").click()
    skill = page.locator('[data-assist-skill-index="0"]')
    skill.fill("11")
    skill.press("Tab")
    page.locator("#preset-run-options summary").click()
    page.locator('[data-run-option="stuckRestart"]').check()
    interval = page.locator('[data-run-option="checkStuckInterval"]')
    interval.fill("")
    interval.press_sequentially("1e")
    interval.press("Tab")
    assert len(pending) == 1
    pending.pop().fulfill(json={"server": "CH", "servants": [{"name": "Support"}]})
    playwright.expect(_slot(page, 0)).to_be_enabled()
    page.locator("#preset-team summary").click()
    _slot(page, 0).select_option("Support")
    playwright.expect(skill).to_have_value("11")
    assert interval.evaluate("e => e.validity.badInput")
    assert _config(page) == {"server": "CH", "round1_turns": 0, "stuckRestart": True, "servant_0_name": "Support"}
    page.close()


def test_catalog_response_during_save_does_not_unlock_team(tag_console):
    browser, url, _directory = tag_console
    page = browser.new_page()
    catalogs = []
    saves = []
    page.route("**/api/servants?*", lambda route: catalogs.append(route))
    page.goto(url)
    page.locator("#edit-setting").click()
    page.route("**/api/settings/demo", lambda route: saves.append(route))
    page.locator("#save-preset").click()
    playwright.expect(page.locator("#preset-assist-slot")).to_be_disabled()
    catalogs.pop().fulfill(json={"server": "CH", "servants": [{"name": "Support"}]})
    playwright.expect(page.locator("#preset-team-status")).to_have_text("1 servants (CH)")
    playwright.expect(_slot(page, 3)).to_be_disabled()
    playwright.expect(page.locator("#preset-assist-slot")).to_be_disabled()
    saves.pop().fulfill(status=500, json={"error": {"message": "Save failed"}})
    playwright.expect(_slot(page, 3)).to_be_enabled()
    page.close()


@pytest.mark.parametrize("field", ["assistIdx", "servant_0_name"])
def test_native_clear_explicit_null_team_field(tag_console, field):
    browser, url, _directory = tag_console
    page = browser.new_page()
    page.goto(url)
    page.locator("#new-setting").click()
    page.locator("#preset-name").fill("Cleared")
    raw = {"server": "CH", "round1_turns": 1, field: None}
    page.locator("#preset-json").fill(json.dumps(raw))
    page.locator("#preset-team summary").click()
    playwright.expect(_slot(page, 0)).to_be_enabled()
    assert _config(page) == raw
    select = page.locator("#preset-assist-slot") if field == "assistIdx" else _slot(page, 0)
    select.focus()
    select.press("Space")
    select.press("Home")
    select.press("Enter")
    expected = {**raw}
    if field == "assistIdx":
        del expected[field]
    else:
        expected[field] = ""
    assert _config(page) == expected
    page.locator("#save-preset").click()
    playwright.expect(page.locator("#preset-dialog")).not_to_be_visible()
    assert page.request.get(f"{url}/api/settings/Cleared").json()["config"] == expected
    page.close()
