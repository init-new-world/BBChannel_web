import json
import os

import pytest

playwright = pytest.importorskip("playwright.sync_api")
from tests.test_assist_tags_browser import tag_console
from tests.test_command_spell_model import NP_SPELL
from tests.test_strategy_assignment_browser import _config, _seed
from tests.test_turn_skills_browser import _open, _row

pytestmark = pytest.mark.skipif(not os.environ.get("BBCHANNEL_TEST_CHROMIUM"), reason="Set BBCHANNEL_TEST_CHROMIUM.")


def _part(page, index, part):
    return _row(page, index).locator(f'[data-turn-skill-part="{part}"]')


@pytest.mark.parametrize("width,locale", [(1440, "en-US"), (390, "zh-CN"), (320, "en-US")])
def test_kukulkan_choice_target_and_domain_edits_preserve_other_source(tag_console, width, locale):
    browser, url, directory = tag_console
    page = browser.new_page(viewport={"width": width, "height": 900}, locale=locale)
    _entries, original = _seed(page, url)
    original["round1_turn0_skill"] = [["Kukulkan", 1, 1], ["Kukulkan", 2, 0, 3], [-2, 3], [NP_SPELL, 2], [12, 1, 4]]
    original["metadata"] = {"float": 1.0, "large": 9007199254740993}
    path = directory / "data" / "settings" / "demo.json"
    path.write_text(json.dumps(original))
    _open(page, url)
    playwright.expect(_part(page, 0, "skill")).to_have_value("Kukulkan:1")
    playwright.expect(_part(page, 0, "named-option")).to_be_checked()
    playwright.expect(_part(page, 0, "target")).to_have_count(0)
    _part(page, 0, "named-option").uncheck()
    assert _config(page)["round1_turn0_skill"][0] == ["Kukulkan", 1, 0]
    assert type(_config(page)["round1_turn0_skill"][0][2]) is int
    _part(page, 0, "skill").select_option("Kukulkan:2")
    playwright.expect(_part(page, 0, "target")).to_have_value("1")
    _part(page, 0, "target").select_option("3")
    _part(page, 0, "named-option").check()
    _part(page, 0, "skill").select_option("Kukulkan:5")
    assert _config(page)["round1_turn0_skill"][0] == ["Kukulkan", 5, 1, 3]
    _part(page, 0, "skill").select_option("Kukulkan:3")
    assert _config(page)["round1_turn0_skill"][0] == ["Kukulkan", 3, 1]
    _part(page, 0, "skill").select_option("Kukulkan:2")
    playwright.expect(_part(page, 0, "target")).to_have_value("1")
    _part(page, 0, "skill").select_option("5")
    playwright.expect(_part(page, 0, "target")).to_have_value("")
    for other in ("13", NP_SPELL, "swap:12", "-2"):
        _part(page, 0, "skill").select_option(other)
        _part(page, 0, "skill").select_option("Kukulkan:2")
        playwright.expect(_part(page, 0, "named-option")).not_to_be_checked()
        playwright.expect(_part(page, 0, "target")).to_have_value("1")
    _part(page, 0, "named-option").check()
    _part(page, 0, "target").select_option("3")
    _row(page, 0).locator('[data-turn-skill-action="down"]').click()
    page.locator("#preset-strategy-target").select_option("round2_extraStrategy")
    page.locator("#add-turn-skill").click()
    _part(page, 0, "skill").select_option("Kukulkan:9")
    _part(page, 0, "named-option").check()
    expected = {**original, "round1_turn0_skill": [["Kukulkan", 2, 0, 3], ["Kukulkan", 2, 1, 3], [-2, 3], [NP_SPELL, 2], [12, 1, 4]],
                "round2_extraSkill": [["Kukulkan", 9, 1]]}
    assert _config(page) == expected
    assert json.loads(path.read_text()) == original
    page.locator("#preset-strategy-target").select_option("round1_turn0_strategy")
    _row(page, 1).scroll_into_view_if_needed()
    settings = _row(page, 1).locator(".turn-skill-named-controls")
    assert settings.evaluate("e => e.scrollWidth <= e.clientWidth")
    page.screenshot(path=str(directory / f"kukulkan-{width}.png"))
    assert page.locator(".preset-form").evaluate("e => e.scrollWidth <= e.clientWidth")
    page.locator("#save-preset").click()
    playwright.expect(page.locator("#preset-dialog")).not_to_be_visible()
    saved = json.loads(path.read_text())
    assert saved == expected
    assert type(saved["metadata"]["float"]) is float
    assert saved["metadata"]["large"] == 9007199254740993
    program = page.request.get(f"{url}/api/settings/demo/program").json()
    assert program["summary"]["unsupported_action_count"] == 0
    assert program["rounds"][0]["turns"][0]["actions"][1]["steps"][-1]["role"] == "skill_target_3"
    extra = program["rounds"][1]["extra_turn"]["actions"][0]
    assert extra["source"]["command"] == ["Kukulkan", 9, 1]
    assert extra["steps"][-1]["role"] == "Kukulkan_option_1"
    page.close()


@pytest.mark.parametrize("command", [["Kukulkan", 1, True], ["Kukulkan", 2, 1], ["Kukulkan", 1, 0.0], ["Kukulkan", 2, 1, 3.0]])
def test_legacy_or_malformed_kukulkan_commands_only_change_after_explicit_clear(tag_console, command):
    browser, url, _directory = tag_console
    page = browser.new_page()
    _seed(page, url)
    _open(page, url)
    source = json.dumps({"server": "CH", "round1_turn0_skill": [command]})
    page.locator("#preset-json").fill(source)
    playwright.expect(page.locator("#add-turn-skill")).to_be_disabled()
    assert page.locator("#preset-json").input_value() == source
    page.once("dialog", lambda dialog: dialog.accept())
    page.locator("#clear-turn-skills").click()
    page.locator("#add-turn-skill").click()
    _part(page, 0, "skill").select_option("Kukulkan:2")
    assert _config(page)["round1_turn0_skill"] == [["Kukulkan", 2, 0, 1]]
    page.close()


def test_kukulkan_checkbox_and_target_lock_during_pending_preset_load(tag_console):
    browser, url, directory = tag_console
    page = browser.new_page()
    _entries, original = _seed(page, url)
    original["round1_turn0_skill"] = [["Kukulkan", 2, 0, 3]]
    (directory / "data" / "settings" / "demo.json").write_text(json.dumps(original))
    _open(page, url)
    response = page.request.get(f"{url}/api/strategies/Preset")
    pending = []
    page.route("**/api/strategies/Preset", lambda route: pending.append(route))
    page.locator("#apply-turn-strategy").click()
    playwright.expect(_part(page, 0, "named-option")).to_be_disabled()
    playwright.expect(_part(page, 0, "target")).to_be_disabled()
    before = page.locator("#preset-json").input_value()
    _part(page, 0, "named-option").evaluate("e => e.dispatchEvent(new Event('change', {bubbles:true}))")
    assert page.locator("#preset-json").input_value() == before
    pending.pop().fulfill(response=response)
    playwright.expect(_part(page, 0, "named-option")).to_be_enabled()
    assert _config(page)["round1_turn0_skill"] == original["round1_turn0_skill"]
    page.close()
