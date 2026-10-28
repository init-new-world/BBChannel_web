import json
import os

import pytest

playwright = pytest.importorskip("playwright.sync_api")
from tests.test_assist_tags_browser import tag_console
from tests.test_command_spell_model import HEAL_SPELL, NP_SPELL
from tests.test_strategy_assignment_browser import _config, _seed
from tests.test_turn_skills_browser import _open, _row

pytestmark = pytest.mark.skipif(not os.environ.get("BBCHANNEL_TEST_CHROMIUM"), reason="Set BBCHANNEL_TEST_CHROMIUM.")


def _part(page, index, part):
    return _row(page, index).locator(f'[data-turn-skill-part="{part}"]')


@pytest.mark.parametrize("width,locale", [(1440, "en-US"), (390, "zh-CN")])
def test_command_spell_edits_keep_target_domains_order_and_original_source(tag_console, width, locale):
    browser, url, directory = tag_console
    page = browser.new_page(viewport={"width": width, "height": 900}, locale=locale)
    _entries, original = _seed(page, url)
    original["round1_turn0_skill"] = [[NP_SPELL, 3], [HEAL_SPELL, 2], [13, 6], [12, 1, 4]]
    original["metadata"] = {"float": 1.0, "large": 9007199254740993}
    path = directory / "data" / "settings" / "demo.json"
    path.write_text(json.dumps(original))
    _open(page, url)
    playwright.expect(_part(page, 0, "skill")).to_have_value(NP_SPELL)
    playwright.expect(_part(page, 0, "target")).to_have_value("3")
    playwright.expect(_part(page, 0, "target").locator("option")).to_have_count(3)
    _part(page, 0, "skill").select_option(HEAL_SPELL)
    playwright.expect(_part(page, 0, "target")).to_have_value("3")
    _part(page, 0, "skill").select_option("12")
    playwright.expect(_part(page, 0, "target")).to_have_value("")
    _part(page, 0, "skill").select_option(NP_SPELL)
    playwright.expect(_part(page, 0, "target")).to_have_value("1")
    _part(page, 0, "target").select_option("2")
    _part(page, 0, "skill").select_option("13")
    playwright.expect(_part(page, 0, "target")).to_have_value("1")
    _part(page, 0, "skill").select_option(HEAL_SPELL)
    playwright.expect(_part(page, 0, "target")).to_have_value("1")
    _part(page, 0, "skill").select_option("swap:12")
    _part(page, 0, "skill").select_option(NP_SPELL)
    playwright.expect(_part(page, 0, "target")).to_have_value("1")
    _row(page, 0).locator('[data-turn-skill-action="down"]').click()
    assert _config(page)["round1_turn0_skill"] == [[HEAL_SPELL, 2], [NP_SPELL, 1], [13, 6], [12, 1, 4]]
    page.locator("#preset-strategy-target").select_option("round2_extraStrategy")
    page.locator("#add-turn-skill").click()
    _part(page, 0, "skill").select_option(HEAL_SPELL)
    _part(page, 0, "target").select_option("3")
    expected = {**original, "round1_turn0_skill": [[HEAL_SPELL, 2], [NP_SPELL, 1], [13, 6], [12, 1, 4]], "round2_extraSkill": [[HEAL_SPELL, 3]]}
    assert _config(page) == expected
    assert json.loads(path.read_text()) == original
    page.locator("#preset-turn-skills").scroll_into_view_if_needed()
    page.screenshot(path=str(directory / f"command-spell-{width}.png"))
    assert page.locator(".preset-form").evaluate("e => e.scrollWidth <= e.clientWidth")
    page.locator("#save-preset").click()
    playwright.expect(page.locator("#preset-dialog")).not_to_be_visible()
    saved = json.loads(path.read_text())
    assert saved == expected
    assert type(saved["metadata"]["float"]) is float
    assert saved["metadata"]["large"] == 9007199254740993
    program = page.request.get(f"{url}/api/settings/demo/program").json()
    assert program["summary"]["unsupported_action_count"] == 0
    assert "command_spell_np_charge" in json.dumps(program)
    assert "command_spell_heal" in json.dumps(program)
    page.close()


@pytest.mark.parametrize("command", [[NP_SPELL, None], [HEAL_SPELL, 4], [NP_SPELL, 1.0], ["future spell", 1]])
def test_unsupported_spell_commands_are_only_replaced_after_explicit_clear(tag_console, command):
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
    _part(page, 0, "skill").select_option(NP_SPELL)
    assert _config(page)["round1_turn0_skill"] == [[NP_SPELL, 1]]
    page.close()
