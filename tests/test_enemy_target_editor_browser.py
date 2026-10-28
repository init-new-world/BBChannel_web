import json
import os

import pytest

playwright = pytest.importorskip("playwright.sync_api")
from tests.test_assist_tags_browser import tag_console
from tests.test_strategy_assignment_browser import _config, _seed
from tests.test_turn_skills_browser import _open, _row

pytestmark = pytest.mark.skipif(not os.environ.get("BBCHANNEL_TEST_CHROMIUM"), reason="Set BBCHANNEL_TEST_CHROMIUM.")


@pytest.mark.parametrize("width,locale", [(1440, "en-US"), (320, "zh-CN")])
def test_enemy_target_commands_keep_domain_order_and_exact_source(tag_console, width, locale):
    browser, url, directory = tag_console
    page = browser.new_page(viewport={"width": width, "height": 900}, locale=locale)
    _entries, original = _seed(page, url)
    original["round1_turn0_skill"] = [[13, 6], [2, 3]]
    original["metadata"] = {"float": 1.0, "large": 9007199254740993}
    path = directory / "data" / "settings" / "demo.json"
    path.write_text(json.dumps(original))
    _open(page, url)
    skill = _row(page, 0).locator('[data-turn-skill-part="skill"]')
    target = _row(page, 0).locator('[data-turn-skill-part="target"]')
    playwright.expect(skill).to_have_value("13")
    playwright.expect(target).to_have_value("6")
    playwright.expect(target.locator("option")).to_have_count(6)
    for slot in range(1, 7):
        target.select_option(str(slot))
        assert _config(page)["round1_turn0_skill"][0] == [13, slot]
    skill.select_option("12")
    playwright.expect(target).to_have_value("")
    assert _config(page)["round1_turn0_skill"] == [12, [2, 3]]
    target.select_option("3")
    skill.select_option("13")
    playwright.expect(target).to_have_value("1")
    assert _config(page)["round1_turn0_skill"] == [[13, 1], [2, 3]]
    _row(page, 0).locator('[data-turn-skill-action="down"]').click()
    assert _config(page)["round1_turn0_skill"] == [[2, 3], [13, 1]]
    page.locator("#preset-strategy-target").select_option("round2_extraStrategy")
    page.locator("#add-turn-skill").click()
    _row(page, 0).locator('[data-turn-skill-part="skill"]').select_option("13")
    _row(page, 0).locator('[data-turn-skill-part="target"]').select_option("5")
    expected = {**original, "round1_turn0_skill": [[2, 3], [13, 1]], "round2_extraSkill": [[13, 5]]}
    assert _config(page) == expected
    assert json.loads(path.read_text()) == original
    assert page.locator(".preset-form").evaluate("e => e.scrollWidth <= e.clientWidth")
    page.locator("#preset-turn-skills").scroll_into_view_if_needed()
    page.screenshot(path=str(directory / f"enemy-target-{width}.png"))
    page.locator("#save-preset").click()
    playwright.expect(page.locator("#preset-dialog")).not_to_be_visible()
    saved = json.loads(path.read_text())
    assert saved == expected
    assert type(saved["metadata"]["float"]) is float
    assert saved["metadata"]["large"] == 9007199254740993
    program = page.request.get(f"{url}/api/settings/demo/program").json()
    assert program["summary"]["unsupported_action_count"] == 0
    assert "enemy_target_1" in json.dumps(program)
    assert "enemy_target_5" in json.dumps(program)
    page.close()
