import json
import os

import pytest

playwright = pytest.importorskip("playwright.sync_api")
from tests.test_assist_tags_browser import tag_console
from tests.test_command_spell_model import NP_SPELL
from tests.test_kukulkan_editor_browser import _part
from tests.test_strategy_assignment_browser import _config, _seed
from tests.test_turn_skills_browser import _open, _row

pytestmark = pytest.mark.skipif(not os.environ.get("BBCHANNEL_TEST_CHROMIUM"), reason="Set BBCHANNEL_TEST_CHROMIUM.")
COMMANDS = [["Barghest", 3, 1], ["BBDubai", 6, 0], ["Soujyuro", 9, "A"], ["Hakuno", 3, "R"]]


@pytest.mark.parametrize("width,locale", [(1440, "en-US"), (390, "zh-CN"), (320, "en-US")])
def test_third_skill_options_transitions_and_source_safe_save(tag_console, width, locale):
    browser, url, directory = tag_console
    page = browser.new_page(viewport={"width": width, "height": 900}, locale=locale)
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    _entries, original = _seed(page, url)
    original["round1_turn0_skill"] = COMMANDS
    original["metadata"] = {"float": 1.0, "large": 9007199254740993}
    path = directory / "data" / "settings" / "demo.json"
    path.write_text(json.dumps(original))
    _open(page, url)
    for index, (named, skill, _option) in enumerate(COMMANDS):
        playwright.expect(_part(page, index, "skill")).to_have_value(f"{named}:{skill}")
        playwright.expect(_part(page, index, "target")).to_have_count(0)
    _part(page, 0, "named-option").uncheck()
    playwright.expect(_part(page, 0, "named-option")).to_be_focused()
    _part(page, 0, "skill").select_option("Barghest:6")
    playwright.expect(_part(page, 0, "named-option")).not_to_be_checked()
    _part(page, 0, "named-option").check()
    _part(page, 0, "skill").select_option("Barghest:9")
    assert _config(page)["round1_turn0_skill"][0] == ["Barghest", 9, 1]
    _part(page, 1, "named-option-1").click()
    playwright.expect(_part(page, 1, "named-option-1")).to_be_focused()
    _part(page, 1, "skill").select_option("BBDubai:3")
    playwright.expect(_part(page, 1, "named-option-1")).to_have_attribute("aria-pressed", "true")
    _part(page, 2, "named-option").select_option("B")
    playwright.expect(_part(page, 2, "named-option")).to_be_focused()
    _part(page, 2, "skill").select_option("Soujyuro:6")
    playwright.expect(_part(page, 2, "named-option")).to_have_value("B")
    playwright.expect(_row(page, 2).locator(".np-color-swatch")).to_have_attribute("data-color", "Buster")
    _part(page, 3, "named-option").select_option("D")
    _part(page, 3, "skill").select_option("Hakuno:9")
    playwright.expect(_part(page, 3, "named-option")).to_have_value("D")
    _row(page, 1).scroll_into_view_if_needed()
    for index in range(4):
        assert _row(page, index).locator(".turn-skill-named-controls").evaluate("e => e.scrollWidth <= e.clientWidth")
    page.screenshot(path=str(directory / f"third-skills-{width}.png"))
    assert page.locator(".preset-form").evaluate("e => e.scrollWidth <= e.clientWidth")
    playwright.expect(_part(page, 1, "named-option-1")).to_have_text("防御类型" if locale == "zh-CN" else "Defense Type")
    _part(page, 0, "skill").select_option("BBDubai:3")
    assert _config(page)["round1_turn0_skill"][0] == ["BBDubai", 3, 0]
    _part(page, 0, "named-option-1").click()
    _part(page, 0, "skill").select_option("Soujyuro:3")
    assert _config(page)["round1_turn0_skill"][0] == ["Soujyuro", 3, "Q"]
    _part(page, 0, "named-option").select_option("A")
    _part(page, 0, "skill").select_option("Hakuno:6")
    assert _config(page)["round1_turn0_skill"][0] == ["Hakuno", 6, "T"]
    _part(page, 0, "named-option").select_option("R")
    _part(page, 0, "skill").select_option("Kukulkan:2")
    assert _config(page)["round1_turn0_skill"][0] == ["Kukulkan", 2, 0, 1]
    _part(page, 0, "named-option").check()
    _part(page, 0, "target").select_option("3")
    for other in ("5", "13", NP_SPELL, "swap:12", "-2"):
        _part(page, 0, "skill").select_option("Barghest:3")
        assert _config(page)["round1_turn0_skill"][0] == ["Barghest", 3, 0]
        _part(page, 0, "named-option").check()
        _part(page, 0, "skill").select_option(other)
        expected = {"5": 5, "13": [13, 1], NP_SPELL: [NP_SPELL, 1], "swap:12": [12, 1, 4], "-2": [-2, 1]}[other]
        assert _config(page)["round1_turn0_skill"][0] == expected
    _part(page, 0, "skill").select_option("Barghest:6")
    _part(page, 0, "named-option").check()
    _row(page, 3).locator('[data-turn-skill-action="up"]').click()
    page.locator("#preset-strategy-target").select_option("round2_extraStrategy")
    page.locator("#add-turn-skill").click()
    _part(page, 0, "skill").select_option("Hakuno:9")
    _part(page, 0, "named-option").select_option("R")
    expected = {**original, "round1_turn0_skill": [["Barghest", 6, 1], ["BBDubai", 3, 1], ["Hakuno", 9, "D"], ["Soujyuro", 6, "B"]],
                "round2_extraSkill": [["Hakuno", 9, "R"]]}
    assert _config(page) == expected
    assert json.loads(path.read_text()) == original
    page.locator("#save-preset").click()
    playwright.expect(page.locator("#preset-dialog")).not_to_be_visible()
    saved = json.loads(path.read_text())
    assert saved == expected
    assert type(saved["metadata"]["float"]) is float
    assert saved["metadata"]["large"] == 9007199254740993
    program = page.request.get(f"{url}/api/settings/demo/program").json()
    assert program["summary"]["unsupported_action_count"] == 0
    actions = program["rounds"][0]["turns"][0]["actions"]
    for action, command in zip(actions, expected["round1_turn0_skill"]):
        assert action["steps"][-1]["role"] == f"{command[0]}_option_{command[2]}"
    assert program["rounds"][1]["extra_turn"]["actions"][0]["source"]["command"] == ["Hakuno", 9, "R"]
    assert errors == []
    page.close()


@pytest.mark.parametrize("command", [["Barghest", 3, True], ["BBDubai", 3, 1.0], ["Barghest", 1, 0],
                                     ["Soujyuro", 3, "Quick"], ["Soujyuro", 3.0, "Q"],
                                     ["Hakuno", 1, [["1B"]]], ["Hakuno", 3, "Q"]])
def test_non_original_third_skill_forms_stay_read_only_until_clear(tag_console, command):
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
    _part(page, 0, "skill").select_option("Soujyuro:3")
    assert _config(page)["round1_turn0_skill"] == [["Soujyuro", 3, "Q"]]
    page.close()


@pytest.mark.parametrize("operation", ["apply", "save"])
def test_third_skill_controls_lock_during_pending_operations(tag_console, operation):
    browser, url, directory = tag_console
    page = browser.new_page()
    _entries, original = _seed(page, url)
    original["round1_turn0_skill"] = COMMANDS
    (directory / "data" / "settings" / "demo.json").write_text(json.dumps(original))
    _open(page, url)
    pending = []
    if operation == "apply":
        response = page.request.get(f"{url}/api/strategies/Preset")
        page.route("**/api/strategies/Preset", lambda route: pending.append(route))
        page.locator("#apply-turn-strategy").click()
    else:
        page.route("**/api/settings/demo", lambda route: pending.append(route))
        page.locator("#save-preset").click()
    for index, part in ((0, "named-option"), (1, "named-option-1"), (2, "named-option"), (3, "named-option")):
        playwright.expect(_part(page, index, part)).to_be_disabled()
    before = page.locator("#preset-json").input_value()
    _part(page, 0, "named-option").evaluate("e => e.dispatchEvent(new Event('change', {bubbles:true}))")
    _part(page, 1, "named-option-1").evaluate("e => e.dispatchEvent(new Event('click', {bubbles:true}))")
    assert page.locator("#preset-json").input_value() == before
    if operation == "apply":
        pending.pop().fulfill(response=response)
    else:
        pending.pop().fulfill(status=500, json={"error": {"message": "Save failed"}})
    playwright.expect(_part(page, 1, "named-option-1")).to_be_enabled()
    assert _config(page)["round1_turn0_skill"] == COMMANDS
    page.close()
