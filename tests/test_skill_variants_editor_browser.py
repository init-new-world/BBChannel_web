import json
import os

import pytest

playwright = pytest.importorskip("playwright.sync_api")
from tests.test_assist_tags_browser import tag_console
from tests.test_kukulkan_editor_browser import _part
from tests.test_strategy_assignment_browser import _config, _seed
from tests.test_turn_skills_browser import _open, _row

pytestmark = pytest.mark.skipif(not os.environ.get("BBCHANNEL_TEST_CHROMIUM"), reason="Set BBCHANNEL_TEST_CHROMIUM.")
COMMANDS = [["VanGoghMiner", 1, "Q"], ["Dante", 5, "B"], ["Gyokuto", 8, "One"],
            ["Charlotte", 3, "\u66b4"], ["Flora", 6, "D"]]


@pytest.mark.parametrize("width,locale", [(1440, "en-US"), (390, "zh-CN"), (320, "en-US"),
                                        (320, "zh-CN"), (760, "en-US"), (761, "en-US")])
def test_variant_skill_options_remain_distinct_across_families_and_save_source_safely(tag_console, width, locale):
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
    for index, (named, skill, option) in enumerate(COMMANDS):
        playwright.expect(_part(page, index, "skill")).to_have_value(f"{named}:{skill}")
        playwright.expect(_part(page, index, "named-option")).to_have_value(option)
        playwright.expect(_part(page, index, "target")).to_have_count(0)
    edits = [("VanGoghMiner", 7, "B"), ("Dante", 2, "A"), ("Gyokuto", 5, "All"),
             ("Charlotte", 9, "\u5b9d"), ("Flora", 3, "T")]
    for index, (named, skill, option) in enumerate(edits):
        _part(page, index, "named-option").select_option(option)
        playwright.expect(_part(page, index, "named-option")).to_be_focused()
        _part(page, index, "skill").select_option(f"{named}:{skill}")
        assert _config(page)["round1_turn0_skill"][index] == [named, skill, option]
    playwright.expect(_row(page, 0).locator(".np-color-swatch")).to_have_attribute("data-color", "Buster")
    playwright.expect(_row(page, 1).locator(".np-color-swatch")).to_have_attribute("data-color", "Arts")
    playwright.expect(_part(page, 0, "skill")).to_have_attribute("title", "梵高〔矿工〕 / 从者 3 / 技能 1" if locale == "zh-CN" else "Van Gogh (Miner) / Servant 3 / Skill 1")
    playwright.expect(_part(page, 4, "named-option").locator("option:checked")).to_have_text("通常状态" if locale == "zh-CN" else "Normal")
    for index in range(5):
        assert _row(page, index).locator(".turn-skill-named-controls").evaluate("e => e.scrollWidth <= e.clientWidth")
        metrics = _part(page, index, "skill").evaluate("""e => {
            const style = getComputedStyle(e);
            const context = document.createElement('canvas').getContext('2d');
            context.font = `${style.fontWeight} ${style.fontSize} ${style.fontFamily}`;
            return [context.measureText(e.selectedOptions[0].textContent).width,
                e.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight) - 18];
        }""")
        assert metrics[0] <= metrics[1], (width, locale, index, metrics)
    _row(page, 1).scroll_into_view_if_needed()
    page.screenshot(path=str(directory / f"skill-variants-{width}.png"))
    assert page.locator(".preset-form").evaluate("e => e.scrollWidth <= e.clientWidth")
    for named, skill, default, chosen in [("Dante", 2, "A", "B"), ("Gyokuto", 2, "All", "One"),
                                           ("Flora", 3, "T", "D"), ("Hakuno", 3, "T", "R"),
                                           ("Charlotte", 3, "\u6280", "\u66b4"), ("Soujyuro", 3, "Q", "A"),
                                           ("VanGoghMiner", 1, "Q", "B")]:
        _part(page, 0, "skill").select_option(f"{named}:{skill}")
        assert _config(page)["round1_turn0_skill"][0] == [named, skill, default]
        _part(page, 0, "named-option").select_option(chosen)
    _part(page, 0, "skill").select_option("Kukulkan:2")
    assert _config(page)["round1_turn0_skill"][0] == ["Kukulkan", 2, 0, 1]
    _part(page, 0, "named-option").check()
    _part(page, 0, "target").select_option("3")
    _part(page, 0, "skill").select_option("Flora:3")
    assert _config(page)["round1_turn0_skill"][0] == ["Flora", 3, "T"]
    for other, command in (("-2", [-2, 1]), ("swap:12", [12, 1, 4]), ("13", [13, 1]), ("5", 5)):
        _part(page, 0, "skill").select_option(other)
        assert _config(page)["round1_turn0_skill"][0] == command
        _part(page, 0, "skill").select_option("VanGoghMiner:1")
        assert _config(page)["round1_turn0_skill"][0] == ["VanGoghMiner", 1, "Q"]
    _part(page, 0, "skill").select_option("VanGoghMiner:4")
    _part(page, 0, "named-option").select_option("A")
    _row(page, 4).locator('[data-turn-skill-action="up"]').click()
    page.locator("#preset-strategy-target").select_option("round2_extraStrategy")
    page.locator("#add-turn-skill").click()
    _part(page, 0, "skill").select_option("VanGoghMiner:7")
    _part(page, 0, "named-option").select_option("B")
    expected = {**original, "round1_turn0_skill": [["VanGoghMiner", 4, "A"], ["Dante", 2, "A"], ["Gyokuto", 5, "All"],
                                                   ["Flora", 3, "T"], ["Charlotte", 9, "\u5b9d"]],
                "round2_extraSkill": [["VanGoghMiner", 7, "B"]]}
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
    assert program["rounds"][1]["extra_turn"]["actions"][0]["source"]["command"] == ["VanGoghMiner", 7, "B"]
    assert errors == []
    page.close()


@pytest.mark.parametrize("fields,available", [('"server":"CH"', True), ('"server":"JP"', True),
                                              ('"server":"ch"', True), ('"server":"jp"', True),
                                              ('"ser\\u0076er":"JP"', True),
                                              ('"server":"CNTW"', False), ('"server":"Future"', False),
                                              ('"server":" CH "', False), ('"server":null', False), ("", False),
                                              ('"server":["CH"]', False), ('"server":"CH","server":"JP"', False),
                                              ('"server":"CH","ser\\u0076er":"CH"', False)])
def test_new_charlotte_selection_requires_an_unambiguous_supported_server_without_rewriting_existing_commands(tag_console, fields, available):
    browser, url, _directory = tag_console
    page = browser.new_page()
    _seed(page, url)
    _open(page, url)
    commands = [1, ["Charlotte", 3, "\u66b4"]]
    source = "{" + (fields + "," if fields else "") + '"round1_turns":1,"round1_turn0_skill":' + json.dumps(commands) + ',"metadata":1.0}'
    page.locator("#preset-json").fill(source)
    playwright.expect(_part(page, 1, "skill")).to_have_value("Charlotte:3")
    assert page.locator("#preset-json").input_value() == source
    for number in (3, 6, 9):
        playwright.expect(_part(page, 0, "skill").locator(f'option[value="Charlotte:{number}"]')).to_have_js_property("disabled", not available)
    _part(page, 1, "named-option").select_option("\u5b9d")
    assert _config(page)["round1_turn0_skill"][1] == ["Charlotte", 3, "\u5b9d"]
    _part(page, 0, "skill").select_option("VanGoghMiner:1")
    assert _config(page)["round1_turn0_skill"][0] == ["VanGoghMiner", 1, "Q"]
    before = page.locator("#preset-json").input_value()
    if available:
        _part(page, 0, "skill").select_option("Charlotte:6")
        assert _config(page)["round1_turn0_skill"][0] == ["Charlotte", 6, "\u6280"]
    else:
        _part(page, 0, "skill").evaluate("e => { e.value = 'Charlotte:6'; e.dispatchEvent(new Event('change', {bubbles:true})); }")
        assert page.locator("#preset-json").input_value() == before
    assert type(_config(page)["metadata"]) is float
    page.close()


def test_team_server_change_updates_charlotte_availability_without_changing_existing_skills(tag_console):
    browser, url, directory = tag_console
    page = browser.new_page()
    _entries, original = _seed(page, url)
    original["round1_turn0_skill"] = COMMANDS
    (directory / "data" / "settings" / "demo.json").write_text(json.dumps(original))
    _open(page, url)
    page.locator("#preset-team summary").click()
    page.locator("#preset-server").select_option("CNTW")
    playwright.expect(_part(page, 0, "skill").locator('option[value="Charlotte:3"]')).to_be_disabled()
    assert _config(page) == {**original, "server": "CNTW"}
    playwright.expect(_part(page, 3, "named-option")).to_have_value("\u66b4")
    page.locator("#preset-server").select_option("JP")
    playwright.expect(_part(page, 0, "skill").locator('option[value="Charlotte:3"]')).to_be_enabled()
    assert _config(page) == {**original, "server": "JP"}
    page.close()


@pytest.mark.parametrize("command", [["VanGoghMiner", 2, "Q"], ["Dante", 1, "A"], ["Gyokuto", 2, "all"],
                                     ["Charlotte", 1, "\u6280"], ["Flora", 3, "R"], ["VanGoghMiner", 1.0, "Q"],
                                     ["Charlotte", 3, True], ["Flora", 3, "T", 1]])
def test_non_original_skill_variants_remain_read_only_until_explicit_clear(tag_console, command):
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
    _part(page, 0, "skill").select_option("Flora:3")
    assert _config(page)["round1_turn0_skill"] == [["Flora", 3, "T"]]
    page.close()


def test_skill_variant_options_lock_during_pending_strategy_load(tag_console):
    browser, url, directory = tag_console
    page = browser.new_page()
    _entries, original = _seed(page, url)
    original["round1_turn0_skill"] = COMMANDS
    (directory / "data" / "settings" / "demo.json").write_text(json.dumps(original))
    _open(page, url)
    response = page.request.get(f"{url}/api/strategies/Preset")
    pending = []
    page.route("**/api/strategies/Preset", lambda route: pending.append(route))
    page.locator("#apply-turn-strategy").click()
    for index in range(5):
        playwright.expect(_part(page, index, "named-option")).to_be_disabled()
    before = page.locator("#preset-json").input_value()
    _part(page, 0, "named-option").evaluate("e => e.dispatchEvent(new Event('change', {bubbles:true}))")
    assert page.locator("#preset-json").input_value() == before
    pending.pop().fulfill(response=response)
    playwright.expect(_part(page, 0, "named-option")).to_be_enabled()
    assert _config(page)["round1_turn0_skill"] == COMMANDS
    page.close()
