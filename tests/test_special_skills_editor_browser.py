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
def test_special_skill_color_edits_keep_semantic_color_and_other_command_domains(tag_console, width, locale):
    browser, url, directory = tag_console
    page = browser.new_page(viewport={"width": width, "height": 900}, locale=locale)
    _entries, original = _seed(page, url)
    original["round1_turn0_skill"] = [[-2, 2], [-3, 2], [NP_SPELL, 2]]
    original["metadata"] = {"float": 1.0, "large": 9007199254740993}
    path = directory / "data" / "settings" / "demo.json"
    path.write_text(json.dumps(original))
    _open(page, url)
    playwright.expect(_part(page, 0, "skill")).to_have_value("-2")
    playwright.expect(_part(page, 0, "choice")).to_have_value("2")
    playwright.expect(_part(page, 0, "choice").locator("option")).to_have_count(3)
    _part(page, 0, "skill").select_option("-3")
    playwright.expect(_part(page, 0, "choice")).to_have_value("1")
    playwright.expect(_part(page, 0, "choice").locator("option")).to_have_count(2)
    _part(page, 0, "choice").select_option("2")
    _part(page, 0, "skill").select_option("-2")
    playwright.expect(_part(page, 0, "choice")).to_have_value("3")
    playwright.expect(_row(page, 0).locator(".np-color-swatch")).to_have_attribute("data-color", "Buster")
    assert _row(page, 0).locator(".np-color-swatch").evaluate("e => getComputedStyle(e).backgroundColor") == "rgb(197, 66, 66)"
    _part(page, 0, "skill").select_option("13")
    playwright.expect(_part(page, 0, "target")).to_have_value("1")
    _part(page, 0, "skill").select_option("-2")
    playwright.expect(_part(page, 0, "choice")).to_have_value("1")
    _part(page, 0, "skill").select_option(NP_SPELL)
    playwright.expect(_part(page, 0, "target")).to_have_value("1")
    _part(page, 0, "skill").select_option("-2")
    _part(page, 0, "choice").select_option("3")
    _row(page, 0).locator('[data-turn-skill-action="down"]').click()
    page.locator("#preset-strategy-target").select_option("round2_extraStrategy")
    page.locator("#add-turn-skill").click()
    _part(page, 0, "skill").select_option("-9")
    _part(page, 0, "choice").select_option("2")
    expected = {**original, "round1_turn0_skill": [[-3, 2], [-2, 3], [NP_SPELL, 2]], "round2_extraSkill": [[-9, 2]]}
    assert _config(page) == expected
    assert json.loads(path.read_text()) == original
    page.locator("#preset-turn-skills").scroll_into_view_if_needed()
    page.screenshot(path=str(directory / f"special-skill-{width}.png"))
    assert page.locator(".preset-form").evaluate("e => e.scrollWidth <= e.clientWidth")
    page.locator("#save-preset").click()
    playwright.expect(page.locator("#preset-dialog")).not_to_be_visible()
    saved = json.loads(path.read_text())
    assert saved == expected
    assert type(saved["metadata"]["float"]) is float
    assert saved["metadata"]["large"] == 9007199254740993
    program = page.request.get(f"{url}/api/settings/demo/program").json()
    assert program["summary"]["unsupported_action_count"] == 0
    assert "special_skill_option_2" in json.dumps(program)
    assert "special_skill_option_3" in json.dumps(program)
    page.close()


@pytest.mark.parametrize("command", [[-1, 1], [-2, 4], [-3, 3], [-2, True], [-2.0, 1], [-2, 1.0]])
def test_invalid_special_skill_pairs_remain_read_only_until_cleared(tag_console, command):
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
    _part(page, 0, "skill").select_option("-2")
    assert _config(page)["round1_turn0_skill"] == [[-2, 1]]
    page.close()
