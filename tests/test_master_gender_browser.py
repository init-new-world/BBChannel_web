import json
import os

import pytest

playwright = pytest.importorskip("playwright.sync_api")
from tests.test_assist_tags_browser import tag_console
from tests.test_master_editor_browser import _masters
from tests.test_strategy_assignment_browser import _config, _seed

pytestmark = pytest.mark.skipif(not os.environ.get("BBCHANNEL_TEST_CHROMIUM"), reason="Set BBCHANNEL_TEST_CHROMIUM.")


def _open(page, url):
    page.goto(url)
    page.locator("#edit-setting").click()
    page.locator("#preset-team summary").click()
    gender = page.locator("#preset-master-sex")
    playwright.expect(gender).to_be_attached(timeout=1000)
    return gender


@pytest.mark.parametrize("width,height,locale", [(1440, 1000, "en-US"), (390, 844, "zh-CN")])
def test_master_gender_default_is_draft_only_and_explicit_changes_save_numbers(tag_console, width, height, locale):
    browser, url, directory = tag_console
    _masters(directory)
    (directory / "data" / "servant_info_JP.json").write_bytes((directory / "data" / "servant_info_CH.json").read_bytes())
    page = browser.new_page(viewport={"width": width, "height": height}, locale=locale)
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    _entries, original = _seed(page, url)
    original.update({"master_equip": "7", "custom": {"keep": 1}})
    assert page.request.put(f"{url}/api/settings/demo", data={"config": original, "overwrite": True}).ok
    gender = _open(page, url)
    playwright.expect(gender).to_have_value("0")
    playwright.expect(gender.locator("option:checked")).to_have_text("女性" if locale == "zh-CN" else "Female")
    assert _config(page) == original
    gender.focus()
    gender.select_option("1")
    playwright.expect(gender).to_be_focused()
    assert _config(page) == {**original, "master_sex": 1}
    assert page.request.get(f"{url}/api/settings/demo").json()["config"] == original
    page.locator("#preset-server").select_option("JP")
    playwright.expect(gender).to_have_value("1")
    outfit = page.locator("#preset-master-equip")
    playwright.expect(outfit).to_be_enabled()
    outfit.select_option("008")
    expected = {**original, "master_sex": 1, "server": "JP", "master_equip": "008"}
    assert _config(page) == expected
    if locale == "zh-CN":
        playwright.expect(gender.locator("option:checked")).to_have_text("男性")
        playwright.expect(gender.locator("..").locator("span")).to_have_text("御主性别")
    page.locator("#preset-team").scroll_into_view_if_needed()
    page.screenshot(path=str(directory / f"master-gender-{width}.png"))
    assert page.locator(".preset-form").evaluate("e => e.scrollWidth <= e.clientWidth")
    page.locator("#save-preset").click()
    playwright.expect(page.locator("#preset-dialog")).not_to_be_visible()
    plan = page.request.get(f"{url}/api/settings/demo/plan")
    assert plan.ok, plan.json()
    assert plan.json()["master"]["sex"] == 1
    gender = _open(page, url)
    gender.select_option("0")
    assert _config(page)["master_sex"] == 0
    page.locator("#cancel-preset").click()
    assert page.request.get(f"{url}/api/settings/demo").json()["config"] == expected
    assert errors == []
    page.close()


@pytest.mark.parametrize("value", [None, False, True, "1", 2, {}, [1]])
def test_legacy_master_gender_is_preserved_until_explicit_replacement(tag_console, value):
    browser, url, directory = tag_console
    _masters(directory)
    page = browser.new_page()
    _entries, original = _seed(page, url)
    original.update({"master_sex": value, "master_equip": 7})
    assert page.request.put(f"{url}/api/settings/demo", data={"config": original, "overwrite": True}).ok
    gender = _open(page, url)
    playwright.expect(gender.locator("option:checked")).to_contain_text("current")
    assert _config(page) == original
    page.locator("#save-preset").click()
    playwright.expect(page.locator("#preset-dialog")).not_to_be_visible()
    assert page.request.get(f"{url}/api/settings/demo").json()["config"] == original
    gender = _open(page, url)
    outfit = page.locator("#preset-master-equip")
    playwright.expect(outfit).to_be_enabled()
    outfit.select_option("0")
    assert _config(page) == {**original, "master_equip": 0}
    gender.select_option("0")
    assert _config(page) == {**original, "master_equip": 0, "master_sex": 0}
    assert type(_config(page)["master_sex"]) is int
    page.locator("#save-preset").click()
    playwright.expect(page.locator("#preset-dialog")).not_to_be_visible()
    saved = page.request.get(f"{url}/api/settings/demo").json()["config"]
    assert saved == {**original, "master_equip": 0, "master_sex": 0}
    assert type(saved["master_sex"]) is int
    page.close()


def test_gender_changes_survive_late_catalog_and_keep_invalid_numeric_drafts(tag_console):
    browser, url, _directory = tag_console
    page = browser.new_page()
    _entries, original = _seed(page, url)
    pending = []
    page.route("**/api/masters", lambda route: pending.append(route))
    gender = _open(page, url)
    playwright.expect(page.locator("#preset-master-equip")).to_be_disabled()
    playwright.expect(gender).to_be_enabled()
    skill = page.locator('[data-assist-skill-index="0"]')
    skill.fill("11")
    skill.press("Tab")
    gender.select_option("1")
    pending.pop().fulfill(status=503, json={"error": {"message": "Outfit offline"}})
    playwright.expect(page.locator("#preset-master-status")).to_contain_text("Outfit offline")
    playwright.expect(gender).to_have_value("1")
    playwright.expect(gender).to_be_enabled()
    gender.select_option("0")
    assert _config(page) == {**original, "master_sex": 0}
    gender.select_option("1")
    playwright.expect(skill).to_have_value("11")
    assert _config(page) == {**original, "master_sex": 1}
    page.locator("#retry-master-catalog").click()
    replacement = {**original, "master_sex": 0, "custom": "raw"}
    page.locator("#preset-json").fill(json.dumps(replacement))
    pending.pop().fulfill(json={"masters": [{"name": "Fresh", "sn": 7}]})
    playwright.expect(page.locator("#preset-master-equip")).to_be_enabled()
    playwright.expect(gender).to_have_value("0")
    assert _config(page) == replacement
    page.close()


def test_master_gender_locks_during_apply_save_and_invalid_json(tag_console):
    browser, url, _directory = tag_console
    page = browser.new_page()
    _seed(page, url)
    gender = _open(page, url)
    pending = []
    response = page.request.get(f"{url}/api/strategies/Preset")
    page.route("**/api/strategies/Preset", lambda route: pending.append(route))
    page.locator("#apply-turn-strategy").click()
    playwright.expect(gender).to_be_disabled()
    pending.pop().fulfill(response=response)
    playwright.expect(gender).to_be_enabled()
    page.locator("#preset-json").fill("{")
    playwright.expect(gender).to_be_disabled()
    page.locator("#preset-json").fill(json.dumps({"server": "CH", "round1_turns": 0, "master_sex": 1}))
    playwright.expect(gender).to_be_enabled()
    page.route("**/api/settings/demo", lambda route: pending.append(route))
    page.locator("#save-preset").click()
    playwright.expect(gender).to_be_disabled()
    pending.pop().fulfill(status=500, json={"error": {"message": "Save failed"}})
    playwright.expect(gender).to_be_enabled()
    playwright.expect(gender).to_have_value("1")
    page.close()
