import json
import os

import pytest

playwright = pytest.importorskip("playwright.sync_api")
from tests.test_assist_tags_browser import tag_console
from tests.test_strategy_assignment_browser import _config, _seed
from tests.test_turn_skills_browser import _open, _row

pytestmark = pytest.mark.skipif(not os.environ.get("BBCHANNEL_TEST_CHROMIUM"), reason="Set BBCHANNEL_TEST_CHROMIUM.")


def _part(page, index, part):
    return _row(page, index).locator(f'[data-turn-skill-part="{part}"]')


@pytest.mark.parametrize("width,locale", [(1440, "en-US"), (390, "zh-CN"), (320, "en-US")])
def test_order_change_edits_keep_positions_nps_and_exact_other_source(tag_console, width, locale):
    browser, url, directory = tag_console
    page = browser.new_page(viewport={"width": width, "height": 900}, locale=locale)
    _entries, original = _seed(page, url)
    original["round1_turn0_skill"] = [[12, 4, 1], 3]
    original["metadata"] = {"float": 1.0, "large": 9007199254740993}
    path = directory / "data" / "settings" / "demo.json"
    raw = json.dumps(original)
    path.write_text(raw)
    _open(page, url)
    playwright.expect(_part(page, 0, "skill")).to_have_value("swap:12")
    playwright.expect(_part(page, 0, "front")).to_have_value("1")
    playwright.expect(_part(page, 0, "reserve")).to_have_value("4")
    assert page.locator("#preset-json").input_value() == raw
    playwright.expect(_part(page, 0, "front").locator("option")).to_have_count(3)
    playwright.expect(_part(page, 0, "reserve").locator("option")).to_have_count(3)
    _part(page, 0, "front").select_option("3")
    _part(page, 0, "reserve").select_option("6")
    assert _config(page)["round1_turn0_skill"] == [[12, 3, 6], 3]
    _part(page, 0, "skill").select_option("swap:10")
    assert _config(page)["round1_turn0_skill"] == [[10, 3, 6], 3]
    _part(page, 0, "skill").select_option("12")
    assert _config(page)["round1_turn0_skill"] == [12, 3]
    _part(page, 0, "skill").select_option("swap:12")
    assert _config(page)["round1_turn0_skill"] == [[12, 1, 4], 3]
    _part(page, 0, "skill").select_option("13")
    assert _config(page)["round1_turn0_skill"] == [[13, 1], 3]
    _part(page, 0, "skill").select_option("swap:10")
    _row(page, 0).locator('[data-turn-skill-action="down"]').click()
    assert _config(page)["round1_turn0_skill"] == [3, [10, 1, 4]]
    page.locator("#preset-strategy-target").select_option("round2_extraStrategy")
    page.locator("#add-turn-skill").click()
    _part(page, 0, "skill").select_option("swap:11")
    _part(page, 0, "front").select_option("2")
    _part(page, 0, "reserve").select_option("6")
    expected = {**original, "round1_turn0_skill": [3, [10, 1, 4]], "round2_extraSkill": [[11, 2, 6]]}
    assert _config(page) == expected
    assert json.loads(path.read_text()) == original
    page.locator("#preset-turn-skills").scroll_into_view_if_needed()
    page.screenshot(path=str(directory / f"turn-exchange-{width}.png"))
    assert page.locator(".preset-form").evaluate("e => e.scrollWidth <= e.clientWidth")
    page.locator("#save-preset").click()
    playwright.expect(page.locator("#preset-dialog")).not_to_be_visible()
    saved = json.loads(path.read_text())
    assert saved == expected
    assert type(saved["metadata"]["float"]) is float
    assert saved["metadata"]["large"] == 9007199254740993
    program = page.request.get(f"{url}/api/settings/demo/program").json()
    assert program["summary"]["unsupported_action_count"] == 0
    assert program["rounds"][0]["turns"][0]["actions"][1]["state_change"] == {"type": "servant_exchange", "positions": [1, 4]}
    assert program["rounds"][1]["extra_turn"]["actions"][0]["state_change"] == {"type": "servant_exchange", "positions": [2, 6]}
    page.close()


def test_order_change_targets_lock_during_pending_save_and_invalid_json(tag_console):
    browser, url, directory = tag_console
    page = browser.new_page()
    _entries, original = _seed(page, url)
    original["round1_turn0_skill"] = [[12, 1, 4]]
    (directory / "data" / "settings" / "demo.json").write_text(json.dumps(original))
    _open(page, url)
    pending = []
    page.route("**/api/settings/demo", lambda route: pending.append(route))
    page.locator("#save-preset").click()
    playwright.expect(_part(page, 0, "front")).to_be_disabled()
    playwright.expect(_part(page, 0, "reserve")).to_be_disabled()
    before = page.locator("#preset-json").input_value()
    _part(page, 0, "front").evaluate("e => {e.value='2'; e.dispatchEvent(new Event('change', {bubbles:true}));}")
    assert page.locator("#preset-json").input_value() == before
    pending.pop().fulfill(status=500, json={"error": {"message": "Save failed"}})
    playwright.expect(_part(page, 0, "front")).to_be_enabled()
    _part(page, 0, "front").select_option("3")
    assert _config(page)["round1_turn0_skill"] == [[12, 3, 4]]
    page.locator("#preset-json").fill("{")
    playwright.expect(page.locator("#add-turn-skill")).to_be_disabled()
    playwright.expect(page.locator("#clear-turn-skills")).to_be_disabled()
    page.close()
