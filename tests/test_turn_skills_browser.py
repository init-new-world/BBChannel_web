import json
import os

import pytest

playwright = pytest.importorskip("playwright.sync_api")
from tests.test_assist_tags_browser import tag_console
from tests.test_strategy_assignment_browser import _config, _seed

pytestmark = pytest.mark.skipif(not os.environ.get("BBCHANNEL_TEST_CHROMIUM"), reason="Set BBCHANNEL_TEST_CHROMIUM.")


def _open(page, url):
    page.goto(url)
    page.locator("#edit-setting").click()
    section = page.locator("#preset-turn-skills")
    playwright.expect(section).to_be_attached(timeout=1000)
    section.locator("summary").click()


def _row(page, index):
    return page.locator(f'[data-turn-skill-index="{index}"]')


@pytest.mark.parametrize("width,height,locale", [(1440, 1000, "en-US"), (390, 844, "zh-CN")])
def test_turn_skill_edits_keep_order_targets_other_turns_and_numeric_source(tag_console, width, height, locale):
    browser, url, directory = tag_console
    page = browser.new_page(viewport={"width": width, "height": height}, locale=locale)
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    _entries, original = _seed(page, url)
    original["metadata"] = {"large": 9007199254740993, "float": 1.0}
    path = directory / "data" / "settings" / "demo.json"
    path.write_text(json.dumps(original, indent=2))
    _open(page, url)
    add = page.locator("#add-turn-skill")
    playwright.expect(add).to_be_enabled()
    assert _config(page) == original
    add.click()
    playwright.expect(_row(page, 0).locator('[data-turn-skill-part="skill"]')).to_be_focused()
    add.click()
    _row(page, 1).locator('[data-turn-skill-part="skill"]').select_option("12")
    _row(page, 1).locator('[data-turn-skill-part="target"]').select_option("3")
    assert _config(page)["round1_turn0_skill"] == [1, [12, 3]]
    _row(page, 1).locator('[data-turn-skill-action="up"]').click()
    assert _config(page)["round1_turn0_skill"] == [[12, 3], 1]
    _row(page, 1).locator('[data-turn-skill-action="remove"]').click()
    playwright.expect(_row(page, 0).locator('[data-turn-skill-part="skill"]')).to_have_value("12")
    playwright.expect(_row(page, 0).locator('[data-turn-skill-part="target"]')).to_have_value("3")
    target = page.locator("#preset-strategy-target")
    target.select_option("round2_extraStrategy")
    add.click()
    _row(page, 0).locator('[data-turn-skill-part="skill"]').select_option("4")
    target.select_option("round1_turn0_strategy")
    playwright.expect(_row(page, 0).locator('[data-turn-skill-part="skill"]')).to_have_value("12")
    expected = {**original, "round1_turn0_skill": [[12, 3]], "round2_extraSkill": [4]}
    assert _config(page) == expected
    assert json.loads(path.read_text()) == original
    page.locator("#preset-turn-skills").scroll_into_view_if_needed()
    page.screenshot(path=str(directory / f"turn-skills-{width}.png"))
    assert page.locator(".preset-form").evaluate("e => e.scrollWidth <= e.clientWidth")
    if locale == "zh-CN":
        playwright.expect(page.locator("#preset-turn-skills summary")).to_contain_text("技能顺序")
    page.locator("#save-preset").click()
    playwright.expect(page.locator("#preset-dialog")).not_to_be_visible()
    saved = json.loads(path.read_text())
    assert saved == expected
    assert type(saved["metadata"]["float"]) is float
    assert saved["metadata"]["large"] == 9007199254740993
    assert page.request.get(f"{url}/api/settings/demo/program").json()["summary"]["unsupported_action_count"] == 0
    assert errors == []
    page.close()


@pytest.mark.parametrize("value", [None, "legacy", [True], [1.0], [[1, 2.0]], [1, [13, 0]], [1, ["Start", 1, []], 2, "End"]])
def test_legacy_and_advanced_skills_stay_read_only_until_explicit_clear(tag_console, value):
    browser, url, _directory = tag_console
    page = browser.new_page()
    _seed(page, url)
    _open(page, url)
    source = json.dumps({"server": "CH", "round3_turn2_skill": value, "metadata": {"keep": True}})
    page.locator("#preset-json").fill(source)
    target = page.locator("#preset-strategy-target")
    target.select_option("round3_turn2_strategy")
    playwright.expect(page.locator("#add-turn-skill")).to_be_disabled()
    clear = page.locator("#clear-turn-skills")
    playwright.expect(clear).to_be_enabled()
    assert page.locator("#preset-json").input_value() == source
    page.once("dialog", lambda dialog: dialog.dismiss())
    clear.click()
    assert page.locator("#preset-json").input_value() == source
    page.once("dialog", lambda dialog: dialog.accept())
    clear.click()
    assert _config(page) == {"server": "CH", "round3_turn2_skill": [], "metadata": {"keep": True}}
    playwright.expect(target).to_have_value("round3_turn2_strategy")
    playwright.expect(target.locator("option")).to_have_count(4)
    playwright.expect(clear).to_be_disabled()
    page.locator("#add-turn-skill").click()
    assert _config(page)["round3_turn2_skill"] == [1]
    page.close()


def test_turn_skill_controls_keep_invalid_drafts_and_lock_during_pending_operations(tag_console):
    browser, url, _directory = tag_console
    page = browser.new_page()
    _entries, original = _seed(page, url)
    _open(page, url)
    skill_level = page.locator('[data-assist-skill-index="0"]')
    skill_level.fill("11")
    skill_level.press("Tab")
    add = page.locator("#add-turn-skill")
    add.click()
    playwright.expect(skill_level).to_have_value("11")
    pending = []
    response = page.request.get(f"{url}/api/strategies/Preset")
    page.route("**/api/strategies/Preset", lambda route: pending.append(route))
    page.locator("#apply-turn-strategy").click()
    playwright.expect(add).to_be_disabled()
    playwright.expect(_row(page, 0).locator('[data-turn-skill-part="skill"]')).to_be_disabled()
    before = page.locator("#preset-json").input_value()
    add.evaluate("e => e.dispatchEvent(new Event('click', {bubbles:true}))")
    assert page.locator("#preset-json").input_value() == before
    pending.pop().fulfill(response=response)
    playwright.expect(add).to_be_enabled()
    playwright.expect(skill_level).to_have_value("11")
    page.locator("#save-preset").click()
    playwright.expect(page.locator("#preset-dialog")).to_be_visible()
    assert page.request.get(f"{url}/api/settings/demo").json()["config"] == original
    page.locator("#preset-json").fill(json.dumps({**original, "round1_turn0_skill": [1]}))
    page.route("**/api/settings/demo", lambda route: pending.append(route))
    page.locator("#save-preset").click()
    playwright.expect(add).to_be_disabled()
    pending.pop().fulfill(status=500, json={"error": {"message": "Save failed"}})
    playwright.expect(add).to_be_enabled()
    page.locator("#preset-json").fill("{")
    playwright.expect(add).to_be_disabled()
    playwright.expect(page.locator("#clear-turn-skills")).to_be_disabled()
    page.close()


@pytest.mark.parametrize("source", [
    '{"server":"CH","round01_turn0_skill":[1]}',
    '{"server":"CH","round1_turn0_skill":[1],"round1_turn0_skill":[2]}',
])
def test_ambiguous_or_noncanonical_skill_fields_cannot_be_rewritten(tag_console, source):
    browser, url, _directory = tag_console
    page = browser.new_page()
    _seed(page, url)
    _open(page, url)
    page.locator("#preset-json").fill(source)
    playwright.expect(page.locator("#add-turn-skill")).to_be_disabled()
    playwright.expect(page.locator("#clear-turn-skills")).to_be_disabled()
    assert page.locator("#preset-json").input_value() == source
    page.close()


def test_skill_sequence_bound_prevents_rendering_excessive_rows(tag_console):
    browser, url, _directory = tag_console
    page = browser.new_page()
    _seed(page, url)
    _open(page, url)
    config = {"server": "CH", "round1_turns": 1, "round1_turn0_skill": [1] * 1001}
    page.locator("#preset-json").fill(json.dumps(config))
    playwright.expect(page.locator("[data-turn-skill-index]")).to_have_count(0)
    playwright.expect(page.locator("#preset-turn-skill-status")).to_have_text("Skill sequence exceeds 1,000 entries.")
    playwright.expect(page.locator("#add-turn-skill")).to_be_disabled()
    page.once("dialog", lambda dialog: dialog.accept())
    page.locator("#clear-turn-skills").click()
    assert _config(page) == {**config, "round1_turn0_skill": []}
    playwright.expect(page.locator("#add-turn-skill")).to_be_enabled()
    page.close()


def test_late_strategy_catalog_does_not_discard_a_focused_skill_control(tag_console):
    browser, url, directory = tag_console
    page = browser.new_page()
    _entries, original = _seed(page, url)
    original["round1_turn0_skill"] = [1]
    (directory / "data" / "settings" / "demo.json").write_text(json.dumps(original))
    pending = []
    page.route("**/api/strategies", lambda route: pending.append(route))
    _open(page, url)
    control = _row(page, 0).locator('[data-turn-skill-part="skill"]')
    control.focus()
    pending.pop().fulfill(json={"strategies": [{"name": "Preset", "path": "strategy/Preset.json"}]})
    playwright.expect(page.locator("#preset-strategy-source")).to_have_value("Preset")
    playwright.expect(control).to_be_focused()
    assert _config(page) == original
    page.close()
