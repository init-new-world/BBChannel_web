import json
import os

import pytest
from PIL import Image

playwright = pytest.importorskip("playwright.sync_api")
from tests.test_assist_tags_browser import tag_console
from tests.test_command_tags import _encoded
from tests.test_kukulkan_editor_browser import _part
from tests.test_strategy_assignment_browser import _config, _seed
from tests.test_turn_skills_browser import _open, _row

pytestmark = pytest.mark.skipif(not os.environ.get("BBCHANNEL_TEST_CHROMIUM"), reason="Set BBCHANNEL_TEST_CHROMIUM.")


def _action(page, index, action, card=None):
    selector = f'[data-hakuno-needs-action="{action}"]'
    if card is not None:
        selector += f'[data-hakuno-card-index="{card}"]'
    return _row(page, index).locator(selector)


def _open_needs(page, index):
    root = _row(page, index).locator(".turn-skill-hakuno-controls")
    if not root.evaluate("e => e.open"):
        root.locator("summary").click()


def _seed_needs(page, url, directory):
    _entries, original = _seed(page, url)
    response = page.request.post(f"{url}/api/command-tags/import", data={
        "name": "[Needs]W1280H720DXL10DXR30DYT20DYB40CON805.png",
        "image_base64": _encoded(Image.new("RGB", (20, 20), "blue")),
    })
    assert response.ok, response.text()
    original.update({"specialKeys": [response.json()["template_path"]],
                     "round1_turn0_skill": [["Hakuno", 1, [["1B", "1B"], ["3Q"]]], ["Hakuno", 3, "R"], ["Kukulkan", 2, 0, 3]],
                     "metadata": {"float": 1.0, "large": 9007199254740993}})
    path = directory / "data" / "settings" / "demo.json"
    path.write_text(json.dumps(original))
    return original, path


@pytest.mark.parametrize("width,locale", [(1440, "en-US"), (390, "zh-CN"), (320, "en-US"), (320, "zh-CN")])
def test_hakuno_needs_edit_groups_cards_domains_and_save_without_changing_other_source(tag_console, width, locale):
    browser, url, directory = tag_console
    page = browser.new_page(viewport={"width": width, "height": 900}, locale=locale)
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    original, path = _seed_needs(page, url, directory)
    _open(page, url)
    playwright.expect(_part(page, 0, "skill")).to_have_value("HakunoNeeds:1")
    playwright.expect(_row(page, 0).locator(".turn-skill-hakuno-controls")).to_have_js_property("open", False)
    before = page.locator("#preset-json").input_value()
    _open_needs(page, 0)
    assert page.locator("#preset-json").input_value() == before
    playwright.expect(_part(page, 0, "needs-card-1")).to_have_value("1B")
    before = page.locator("#preset-json").input_value()
    _part(page, 0, "needs-group").select_option("1")
    playwright.expect(_part(page, 0, "needs-group")).to_be_focused()
    playwright.expect(_part(page, 0, "needs-card-0")).to_have_value("3Q")
    assert page.locator("#preset-json").input_value() == before
    _action(page, 0, "add-card").click()
    playwright.expect(_part(page, 0, "needs-card-1")).to_be_focused()
    _part(page, 0, "needs-card-1").select_option("2AS0")
    for _ in range(3):
        _action(page, 0, "add-card").click()
    playwright.expect(_action(page, 0, "add-card")).to_be_disabled()
    assert _config(page)["round1_turn0_skill"][0][2] == [["1B", "1B"], ["3Q", "2AS0", "1B", "1B", "1B"]]
    _part(page, 0, "needs-card-4").scroll_into_view_if_needed()
    root = _row(page, 0).locator(".turn-skill-hakuno-controls")
    assert root.evaluate("e => e.scrollWidth <= e.clientWidth")
    page.screenshot(path=str(directory / f"hakuno-needs-{width}-{locale}.png"))
    assert page.locator(".preset-form").evaluate("e => e.scrollWidth <= e.clientWidth")
    _action(page, 0, "remove-card", 4).click()
    _action(page, 0, "remove-card", 3).click()
    _action(page, 0, "add").click()
    playwright.expect(_part(page, 0, "needs-group")).to_have_value("2")
    _action(page, 0, "up").click()
    playwright.expect(_part(page, 0, "needs-group")).to_have_value("1")
    assert _config(page)["round1_turn0_skill"][0][2] == [["1B", "1B"], ["1B"], ["3Q", "2AS0", "1B"]]
    _action(page, 0, "remove-card", 0).click()
    assert _config(page)["round1_turn0_skill"][0][2] == [["1B", "1B"], ["3Q", "2AS0", "1B"]]
    _action(page, 0, "remove").click()
    _action(page, 0, "remove-card", 1).click()
    _action(page, 0, "remove-card", 0).click()
    assert _config(page)["round1_turn0_skill"][0] == ["Hakuno", 1, []]
    playwright.expect(_part(page, 0, "needs-group")).to_be_disabled()
    playwright.expect(_part(page, 0, "needs-add")).to_be_focused()
    _action(page, 0, "add").click()
    _part(page, 0, "needs-card-0").select_option("S0")
    _part(page, 0, "skill").select_option("HakunoNeeds:4")
    assert _config(page)["round1_turn0_skill"][0] == ["Hakuno", 4, [["S0"]]]
    _part(page, 0, "skill").select_option("Hakuno:3")
    assert _config(page)["round1_turn0_skill"][0] == ["Hakuno", 3, "T"]
    _part(page, 0, "named-option").select_option("R")
    _part(page, 0, "skill").select_option("HakunoNeeds:7")
    assert _config(page)["round1_turn0_skill"][0] == ["Hakuno", 7, []]
    for other, expected in (("Kukulkan:2", ["Kukulkan", 2, 0, 1]), ("-2", [-2, 1]), ("13", [13, 1])):
        _part(page, 0, "skill").select_option(other)
        assert _config(page)["round1_turn0_skill"][0] == expected
        _part(page, 0, "skill").select_option("HakunoNeeds:7")
        assert _config(page)["round1_turn0_skill"][0] == ["Hakuno", 7, []]
    _action(page, 0, "add").click()
    _part(page, 0, "needs-card-0").select_option("1BS0")
    _row(page, 0).locator('[data-turn-skill-action="down"]').click()
    _open_needs(page, 1)
    playwright.expect(_part(page, 1, "needs-card-0")).to_have_value("1BS0")
    page.locator("#preset-strategy-target").select_option("round2_extraStrategy")
    page.locator("#add-turn-skill").click()
    _part(page, 0, "skill").select_option("HakunoNeeds:4")
    _action(page, 0, "add").click()
    _part(page, 0, "needs-card-0").select_option("2AS0")
    _action(page, 0, "add-card").click()
    _part(page, 0, "needs-card-1").select_option("2AS0")
    expected = {**original, "round1_turn0_skill": [["Hakuno", 3, "R"], ["Hakuno", 7, [["1BS0"]]], ["Kukulkan", 2, 0, 3]],
                "round2_extraSkill": [["Hakuno", 4, [["2AS0", "2AS0"]]]]}
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
    assert program["rounds"][0]["turns"][0]["actions"][1]["runtime"]["need_cards"] == [["1BS0"]]
    assert program["rounds"][1]["extra_turn"]["actions"][0]["runtime"]["need_cards"] == [["2AS0", "2AS0"]]
    assert errors == []
    page.close()


@pytest.mark.parametrize("operation", ["apply", "save"])
def test_hakuno_group_selection_and_card_actions_lock_during_pending_operations(tag_console, operation):
    browser, url, directory = tag_console
    page = browser.new_page()
    original, _path = _seed_needs(page, url, directory)
    _open(page, url)
    _open_needs(page, 0)
    pending = []
    if operation == "apply":
        response = page.request.get(f"{url}/api/strategies/Preset")
        page.route("**/api/strategies/Preset", lambda route: pending.append(route))
        page.locator("#apply-turn-strategy").click()
    else:
        page.route("**/api/settings/demo", lambda route: pending.append(route))
        page.locator("#save-preset").click()
    playwright.expect(_part(page, 0, "needs-group")).to_be_disabled()
    playwright.expect(_action(page, 0, "add")).to_be_disabled()
    before = page.locator("#preset-json").input_value()
    _part(page, 0, "needs-group").evaluate("e => {e.value='1';e.dispatchEvent(new Event('change',{bubbles:true}));}")
    _action(page, 0, "add").evaluate("e => e.dispatchEvent(new Event('click',{bubbles:true}))")
    assert page.locator("#preset-json").input_value() == before
    if operation == "apply":
        pending.pop().fulfill(response=response)
    else:
        pending.pop().fulfill(status=500, json={"error": {"message": "Save failed"}})
    playwright.expect(_action(page, 0, "add")).to_be_enabled()
    page.locator("#preset-strategy-target").select_option("round2_extraStrategy")
    page.locator("#preset-strategy-target").select_option("round1_turn0_strategy")
    playwright.expect(_part(page, 0, "needs-group")).to_have_value("0")
    assert _config(page)["round1_turn0_skill"] == original["round1_turn0_skill"]
    page.close()


def test_unbound_but_syntactically_valid_hakuno_codes_are_preserved_as_current_values(tag_console):
    browser, url, _directory = tag_console
    page = browser.new_page()
    _seed(page, url)
    _open(page, url)
    source = '{"server":"CH","round1_turn0_skill":[["Hakuno",1,[["S99","1B"]]]],"metadata":1.0}'
    page.locator("#preset-json").fill(source)
    _open_needs(page, 0)
    playwright.expect(_part(page, 0, "needs-card-0")).to_have_value("S99")
    playwright.expect(_part(page, 0, "needs-card-0").locator("option:checked")).to_be_disabled()
    assert page.locator("#preset-json").input_value() == source
    _part(page, 0, "needs-card-1").select_option("2A")
    assert _config(page)["round1_turn0_skill"] == [["Hakuno", 1, [["S99", "2A"]]]]
    assert type(_config(page)["metadata"]) is float
    page.close()


def test_legacy_empty_hakuno_combination_stays_unchanged_until_explicit_card_edit(tag_console):
    browser, url, _directory = tag_console
    page = browser.new_page()
    _seed(page, url)
    _open(page, url)
    source = '{"server":"CH","round1_turn0_skill":[["Hakuno",1,[[]]]],"metadata":1.0}'
    page.locator("#preset-json").fill(source)
    _open_needs(page, 0)
    playwright.expect(_part(page, 0, "needs-group")).to_be_enabled()
    playwright.expect(_part(page, 0, "needs-card-0")).to_have_count(0)
    assert page.locator("#preset-json").input_value() == source
    _action(page, 0, "add-card").click()
    assert _config(page)["round1_turn0_skill"] == [["Hakuno", 1, [["1B"]]]]
    page.close()


def test_only_one_hakuno_panel_is_populated_and_reopening_the_editor_resets_view_state(tag_console):
    browser, url, directory = tag_console
    page = browser.new_page()
    original, path = _seed_needs(page, url, directory)
    original["round1_turn0_skill"] = [["Hakuno", 1, [["1B"], ["2A"]]], ["Hakuno", 4, [["3Q"], ["S0"]]]]
    path.write_text(json.dumps(original))
    before = path.read_bytes()
    _open(page, url)
    playwright.expect(page.locator(".hakuno-needs-panel")).to_have_count(0)
    source = page.locator("#preset-json").input_value()
    _open_needs(page, 0)
    playwright.expect(page.locator(".hakuno-needs-panel")).to_have_count(1)
    _open_needs(page, 1)
    playwright.expect(_row(page, 0).locator(".turn-skill-hakuno-controls")).to_have_js_property("open", False)
    playwright.expect(page.locator(".hakuno-needs-panel")).to_have_count(1)
    _part(page, 1, "needs-group").select_option("1")
    assert page.locator("#preset-json").input_value() == source
    page.locator("#cancel-preset").click()
    assert path.read_bytes() == before
    page.locator("#edit-setting").click()
    page.locator("#preset-turn-skills > summary").click()
    playwright.expect(page.locator(".hakuno-needs-panel")).to_have_count(0)
    _open_needs(page, 1)
    playwright.expect(_part(page, 1, "needs-group")).to_have_value("0")
    page.close()
