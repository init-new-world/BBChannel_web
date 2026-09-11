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


@pytest.mark.parametrize("width,height", [(1440, 1000), (390, 844)])
def test_edit_np_order_swaps_duplicates_and_preserves_other_turns(tag_console, width, height):
    browser, url, directory = tag_console
    page = browser.new_page(viewport={"width": width, "height": height})
    page.set_default_timeout(10000)
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    _entries, original = _seed(page, url)
    page.goto(url)
    page.locator("#edit-setting").click()
    slots = page.locator("[data-turn-np-index]")
    playwright.expect(slots).to_have_count(3)
    playwright.expect(slots.nth(0)).to_have_value("2")
    playwright.expect(slots.nth(1)).to_have_value("0")
    playwright.expect(slots.nth(2)).to_be_disabled()
    slots.nth(0).select_option("1")
    slots.nth(1).select_option("3")
    slots.nth(2).select_option("2")
    assert _config(page)["round1_turn0_np"] == [1, 3, 2]
    slots.nth(0).select_option("2")
    assert _config(page)["round1_turn0_np"] == [2, 3, 1]
    slots.nth(1).select_option("0")
    assert _config(page)["round1_turn0_np"] == [2, 1]
    target = page.locator("#preset-strategy-target")
    target.select_option("round2_turn0_strategy")
    playwright.expect(slots.nth(0)).to_have_value("0")
    slots.nth(0).select_option("3")
    target.select_option("round2_extraStrategy")
    playwright.expect(page.locator("#preset-turn-nps")).not_to_be_visible()
    target.select_option("round1_turn0_strategy")
    playwright.expect(slots.nth(0)).to_have_value("2")
    playwright.expect(slots.nth(1)).to_have_value("1")
    expected = {**original, "round1_turn0_np": [2, 1], "round2_turn0_np": [3]}
    assert _config(page) == expected
    assert page.request.get(f"{url}/api/settings/demo").json()["config"] == original
    page.locator(".preset-form").evaluate("e => e.scrollTop = 0")
    save_bounds = page.locator("#save-preset").bounding_box()
    dialog_bounds = page.locator("#preset-dialog").bounding_box()
    assert save_bounds["y"] + save_bounds["height"] <= dialog_bounds["y"] + dialog_bounds["height"]
    assert page.locator("#save-preset").evaluate("e => { const r = e.getBoundingClientRect(); return e.contains(document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2)); }")
    page.screenshot(path=str(directory / f"turn-nps-{width}.png"))
    assert page.locator(".preset-form").evaluate("e => e.scrollWidth <= e.clientWidth")
    page.locator("#save-preset").click()
    playwright.expect(page.locator("#preset-dialog")).not_to_be_visible()
    assert page.request.get(f"{url}/api/settings/demo").json()["config"] == expected
    assert errors == []
    page.close()


@pytest.mark.parametrize("invalid", [[1, 1], [True], "invalid", [1, 2, 3, 1], None])
def test_invalid_np_sequences_can_be_cleared_without_removing_inferred_turns(tag_console, invalid):
    browser, url, _directory = tag_console
    page = browser.new_page()
    page.set_default_timeout(10000)
    _seed(page, url)
    page.goto(url)
    page.locator("#edit-setting").click()
    config = {"server": "CH", "round3_turn2_np": invalid, "metadata": {"keep": True}}
    page.locator("#preset-json").fill(json.dumps(config))
    target = page.locator("#preset-strategy-target")
    target.select_option("round3_turn2_strategy")
    playwright.expect(page.locator("#preset-turn-np-status")).to_have_text("Invalid NP sequence.")
    playwright.expect(page.locator("[data-turn-np-index]").nth(0)).to_be_disabled()
    playwright.expect(page.locator("#clear-turn-nps")).to_be_enabled()
    page.once("dialog", lambda dialog: dialog.dismiss())
    page.locator("#clear-turn-nps").click()
    assert _config(page) == config
    page.once("dialog", lambda dialog: dialog.accept())
    page.locator("#clear-turn-nps").click()
    assert _config(page) == {**config, "round3_turn2_np": []}
    playwright.expect(target).to_have_value("round3_turn2_strategy")
    playwright.expect(target.locator("option")).to_have_count(4)
    playwright.expect(page.locator("#clear-turn-nps")).to_be_disabled()
    playwright.expect(page.locator("[data-turn-np-index]").nth(0)).to_be_enabled()
    page.close()


def test_np_edits_preserve_invalid_skill_drafts_and_follow_pending_operations(tag_console):
    browser, url, _directory = tag_console
    page = browser.new_page()
    page.set_default_timeout(10000)
    _entries, original = _seed(page, url)
    page.goto(url)
    page.locator("#edit-setting").click()
    skill = page.locator('[data-assist-skill-index="0"]')
    skill.fill("11")
    skill.press("Tab")
    slot = page.locator("[data-turn-np-index]").nth(0)
    slot.select_option("3")
    playwright.expect(skill).to_have_value("11")
    assert not skill.evaluate("e => e.checkValidity()")
    pending = []
    page.route("**/api/strategies/Preset", lambda route: pending.append(route))
    response = page.request.get(f"{url}/api/strategies/Preset")
    page.locator("#apply-turn-strategy").click()
    playwright.expect(slot).to_be_disabled()
    playwright.expect(page.locator("#clear-turn-nps")).to_be_disabled()
    pending.pop().fulfill(response=response)
    playwright.expect(slot).to_be_enabled()
    playwright.expect(skill).to_have_value("11")
    page.locator("#save-preset").click()
    playwright.expect(page.locator("#preset-dialog")).to_be_visible()
    assert page.request.get(f"{url}/api/settings/demo").json()["config"] == original
    page.locator("#preset-json").fill("{")
    playwright.expect(slot).to_be_disabled()
    page.close()
