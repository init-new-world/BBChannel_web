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


def _row(page, wave):
    return page.locator(f'[data-script-wave="{wave}"]')


def _open_waves(page):
    details = page.locator("#preset-waves")
    if not details.evaluate("e => e.open"):
        details.locator("summary").click()


@pytest.mark.parametrize("width,height", [(1440, 1000), (390, 844)])
def test_create_script_waves_and_turns_without_json(tag_console, width, height):
    browser, url, directory = tag_console
    page = browser.new_page(viewport={"width": width, "height": height})
    page.set_default_timeout(10000)
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(url)
    page.locator("#new-setting").click()
    page.locator("#preset-name").fill("VisualScript")
    playwright.expect(page.locator("#preset-waves")).to_be_visible()
    playwright.expect(_row(page, 1).locator("output")).to_have_text("0 turns")
    _row(page, 1).locator('[data-wave-action="add-turn"]').click()
    playwright.expect(page.locator("#preset-strategy-target")).to_have_value("round1_turn0_strategy")
    page.locator('[data-turn-np-index="0"]').select_option("2")
    page.locator("#add-script-wave").click()
    playwright.expect(page.locator("#preset-strategy-target")).to_have_value("round2_turn0_strategy")
    _row(page, 2).locator('[data-wave-action="add-turn"]').click()
    page.locator('[data-turn-np-index="0"]').select_option("3")
    playwright.expect(_row(page, 1).locator('[data-wave-action="delete-wave"]')).to_be_disabled()
    page.once("dialog", lambda dialog: dialog.dismiss())
    _row(page, 2).locator('[data-wave-action="remove-turn"]').click()
    assert _config(page)["round2_turn1_np"] == [3]
    page.once("dialog", lambda dialog: dialog.accept())
    _row(page, 2).locator('[data-wave-action="remove-turn"]').click()
    expected = {"server": "CH", "round1_turns": 1, "round1_turn0_np": [2], "round2_turns": 1}
    assert _config(page) == expected
    assert page.request.get(f"{url}/api/settings/VisualScript").status == 404
    page.locator(".preset-form").evaluate("e => e.scrollTop = 0")
    footer = page.locator(".preset-dialog-actions").bounding_box()
    form = page.locator(".preset-form").bounding_box()
    assert footer["y"] + footer["height"] >= form["y"] + form["height"] - 1
    page.screenshot(path=str(directory / f"script-waves-{width}.png"))
    assert page.locator(".preset-form").evaluate("e => e.scrollWidth <= e.clientWidth")
    assert page.locator("#preset-wave-list img").evaluate_all("images => images.length > 0 && images.every(e => e.complete && e.naturalWidth > 0)")
    page.locator("#save-preset").click()
    playwright.expect(page.locator("#preset-dialog")).not_to_be_visible()
    assert page.request.get(f"{url}/api/settings/VisualScript").json()["config"] == expected
    assert errors == []
    page.close()


def test_wave_buttons_keep_focus_for_repeated_keyboard_actions(tag_console):
    browser, url, _directory = tag_console
    page = browser.new_page()
    page.set_default_timeout(10000)
    page.goto(url)
    page.locator("#new-setting").click()
    add = _row(page, 1).locator('[data-wave-action="add-turn"]')
    add.click()
    playwright.expect(add).to_be_focused()
    page.keyboard.press("Enter")
    playwright.expect(_row(page, 1).locator("output")).to_have_text("2 turns")
    page.keyboard.press("Space")
    playwright.expect(_row(page, 1).locator("output")).to_have_text("3 turns")
    page.close()


def test_add_wave_and_limit_keep_an_enabled_keyboard_target(tag_console):
    browser, url, _directory = tag_console
    page = browser.new_page()
    page.set_default_timeout(10000)
    page.goto(url)
    page.locator("#new-setting").click()
    add_wave = page.locator("#add-script-wave")
    add_wave.click()
    playwright.expect(add_wave).to_be_focused()
    page.keyboard.press("Enter")
    playwright.expect(page.locator("#preset-wave-list [data-script-wave]")).to_have_count(3)
    page.locator("#preset-json").fill('{"server":"CH","round1_turns":998}')
    _row(page, 1).locator('[data-wave-action="add-turn"]').click()
    playwright.expect(_row(page, 1).locator("output")).to_have_text("999 turns")
    playwright.expect(_row(page, 1).locator('[data-wave-action="remove-turn"]')).to_be_focused()
    page.close()


def test_removing_last_turn_and_wave_preserves_other_scopes(tag_console):
    browser, url, _directory = tag_console
    page = browser.new_page()
    page.set_default_timeout(10000)
    _seed(page, url)
    page.goto(url)
    page.locator("#edit-setting").click()
    config = {
        "server": "CH", "round1_turns": 1, "round1_custom": {"keep": True},
        "round4_turn2_np": [1], "round4_turn2_extension": {"remove": True},
        "round4_turn1_unknown": "keep", "round4_extraStrategy": [],
        "metadata": {"global": True},
    }
    page.locator("#preset-json").fill(json.dumps(config))
    _open_waves(page)
    playwright.expect(_row(page, 4).locator("output")).to_have_text("3 turns")
    page.once("dialog", lambda dialog: dialog.accept())
    _row(page, 4).locator('[data-wave-action="remove-turn"]').click()
    expected = {key: value for key, value in config.items() if not key.startswith("round4_turn2_")}
    expected["round4_turns"] = 2
    assert _config(page) == expected
    page.once("dialog", lambda dialog: dialog.dismiss())
    _row(page, 4).locator('[data-wave-action="delete-wave"]').click()
    assert _config(page) == expected
    page.once("dialog", lambda dialog: dialog.accept())
    _row(page, 4).locator('[data-wave-action="delete-wave"]').click()
    assert _config(page) == {key: value for key, value in config.items() if not key.startswith("round4_")}
    playwright.expect(_row(page, 1).locator('[data-wave-action="delete-wave"]')).to_be_enabled()
    page.once("dialog", lambda dialog: dialog.accept())
    _row(page, 1).locator('[data-wave-action="delete-wave"]').click()
    playwright.expect(page.locator("#preset-wave-list [data-script-wave]")).to_have_count(0)
    page.locator("#add-script-wave").click()
    assert _config(page) == {"server": "CH", "metadata": {"global": True}, "round1_turns": 1}
    page.close()


def test_wave_edits_preserve_invalid_skill_drafts_and_obey_request_locks(tag_console):
    browser, url, _directory = tag_console
    page = browser.new_page()
    page.set_default_timeout(10000)
    _seed(page, url)
    page.goto(url)
    page.locator("#edit-setting").click()
    _open_waves(page)
    skill = page.locator('[data-assist-skill-index="0"]')
    skill.fill("11")
    skill.press("Tab")
    _row(page, 1).locator('[data-wave-action="add-turn"]').click()
    playwright.expect(skill).to_have_value("11")
    assert not skill.evaluate("e => e.checkValidity()")
    pending = []
    page.route("**/api/strategies/Preset", lambda route: pending.append(route))
    response = page.request.get(f"{url}/api/strategies/Preset")
    page.locator("#apply-turn-strategy").click()
    playwright.expect(page.locator("#add-script-wave")).to_be_disabled()
    playwright.expect(_row(page, 1).locator('[data-wave-action="add-turn"]')).to_be_disabled()
    pending.pop().fulfill(response=response)
    playwright.expect(page.locator("#add-script-wave")).to_be_enabled()
    skill.fill("0")
    skill.press("Tab")

    def hold_save(route):
        if route.request.method == "PUT":
            pending.append(route)
        else:
            route.continue_()

    page.route("**/api/settings/demo", hold_save)
    page.locator("#save-preset").click()
    playwright.expect(page.locator("#add-script-wave")).to_be_disabled()
    playwright.expect(_row(page, 1).locator('[data-wave-action="remove-turn"]')).to_be_disabled()
    pending.pop().fulfill(status=500, json={"error": {"message": "Save failed"}})
    playwright.expect(page.locator("#preset-error")).to_have_text("Save failed")
    playwright.expect(page.locator("#add-script-wave")).to_be_enabled()
    page.locator("#preset-json").fill("{")
    playwright.expect(page.locator("#add-script-wave")).to_be_disabled()
    page.locator("#preset-json").fill('{"server":"CH","round1_turns":999}')
    playwright.expect(page.locator("#add-script-wave")).to_be_disabled()
    playwright.expect(_row(page, 1).locator('[data-wave-action="add-turn"]')).to_be_disabled()
    page.locator("#preset-json").fill('{"server":"CH","round01_turn1_np":[1]}')
    playwright.expect(page.locator("#add-script-wave")).to_be_disabled()
    playwright.expect(page.locator("#preset-wave-status")).to_have_text("Wave editing requires canonical round and turn keys.")
    assert _config(page) == {"server": "CH", "round01_turn1_np": [1]}
    page.close()


@pytest.mark.parametrize("fields,message", [
    ({"round1_turns": True}, "Wave turn counts must be non-negative integers."),
    ({"round1_turns": -1}, "Wave turn counts must be non-negative integers."),
    ({"round1_turns": "2"}, "Wave turn counts must be non-negative integers."),
    ({"round1_turn02_np": [1]}, "Wave editing requires canonical round and turn keys."),
    ({"round1_turns": 1, "round1_turn-1_np": [1]}, "Wave editing requires canonical round and turn keys."),
    ({"round1_turns": 1, "round1_turn1.5_np": [1]}, "Wave editing requires canonical round and turn keys."),
    ({"round-1_turn0_np": [1]}, "Wave editing requires canonical round and turn keys."),
    ({"round1_turns": 1, "round1_turn_np": [1]}, "Wave editing requires canonical round and turn keys."),
    ({"round1_turns": 1, "round_turn0_np": [1]}, "Wave editing requires canonical round and turn keys."),
    ({f"round{i}_turns": 0 for i in range(1001)}, "Wave list exceeds 1,000 entries."),
])
def test_invalid_wave_structures_are_not_silently_rewritten(tag_console, fields, message):
    browser, url, _directory = tag_console
    page = browser.new_page()
    page.set_default_timeout(10000)
    page.goto(url)
    page.locator("#new-setting").click()
    source = json.dumps({"server": "CH", **fields})
    page.locator("#preset-json").fill(source)
    playwright.expect(page.locator("#add-script-wave")).to_be_disabled()
    playwright.expect(page.locator("#preset-wave-status")).to_have_text(message)
    assert page.locator("#preset-json").input_value() == source
    page.close()
