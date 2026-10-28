import json
import os

import pytest

playwright = pytest.importorskip("playwright.sync_api")
from tests.test_assist_tags_browser import tag_console
from tests.test_strategy_assignment_browser import _config, _seed

pytestmark = pytest.mark.skipif(not os.environ.get("BBCHANNEL_TEST_CHROMIUM"), reason="Set BBCHANNEL_TEST_CHROMIUM.")


@pytest.mark.parametrize("width,locale", [(1440, "en-US"), (390, "zh-CN")])
def test_np_edit_and_save_keep_unrelated_numeric_types_and_skill_meaning(tag_console, width, locale):
    browser, url, directory = tag_console
    page = browser.new_page(viewport={"width": width, "height": 900}, locale=locale)
    _entries, original = _seed(page, url)
    original["metadata"] = {"float": 1.0, "large": 9007199254740993}
    original["round1_turn0_skill"] = [1.0]
    path = directory / "data" / "settings" / "demo.json"
    path.write_text(json.dumps(original))
    page.goto(url)
    page.locator("#edit-setting").click()
    slot = page.locator("[data-turn-np-index]").nth(0)
    slot.select_option("3")
    assert _config(page)["metadata"] == original["metadata"]
    assert type(_config(page)["metadata"]["float"]) is float
    assert type(_config(page)["round1_turn0_skill"][0]) is float
    playwright.expect(page.locator("#add-turn-skill")).to_be_disabled()
    playwright.expect(slot.locator("option:checked")).to_have_text("宝具 3" if locale == "zh-CN" else "NP 3")
    assert json.loads(path.read_text()) == original
    page.locator("#preset-turn-nps").scroll_into_view_if_needed()
    page.screenshot(path=str(directory / f"np-source-{width}.png"))
    assert page.locator(".preset-form").evaluate("e => e.scrollWidth <= e.clientWidth")
    page.locator("#save-preset").click()
    playwright.expect(page.locator("#preset-dialog")).not_to_be_visible()
    saved = json.loads(path.read_text())
    assert saved == {**original, "round1_turn0_np": [3]}
    assert type(saved["metadata"]["float"]) is float
    assert type(saved["round1_turn0_skill"][0]) is float
    assert page.request.get(f"{url}/api/settings/demo/program").json()["summary"]["unsupported_action_count"] == 1
    page.close()


@pytest.mark.parametrize("source", [
    '{"server":"CH","round1_turn0_np":[1.0]}',
    '{"server":"CH","round1_turn0_np":[1e0]}',
    '{"server":"CH","round1_turn0_np":[1],"round1_turn0_np":[2]}',
    '{"server":"CH","round01_turn0_np":[1]}',
])
def test_np_type_or_field_ambiguity_is_not_silently_rewritten(tag_console, source):
    browser, url, _directory = tag_console
    page = browser.new_page()
    _seed(page, url)
    page.goto(url)
    page.locator("#edit-setting").click()
    page.locator("#preset-json").fill(source)
    playwright.expect(page.locator("[data-turn-np-index]").nth(0)).to_be_disabled()
    if "round01_" in source or source.count('"round1_turn0_np"') == 2:
        playwright.expect(page.locator("#clear-turn-nps")).to_be_disabled()
    else:
        page.once("dialog", lambda dialog: dialog.accept())
        page.locator("#clear-turn-nps").click()
        assert _config(page)["round1_turn0_np"] == []
    page.close()


def test_late_strategy_catalog_does_not_blur_a_focused_np_slot(tag_console):
    browser, url, _directory = tag_console
    page = browser.new_page()
    _seed(page, url)
    pending = []
    page.route("**/api/strategies", lambda route: pending.append(route))
    page.goto(url)
    page.locator("#edit-setting").click()
    slot = page.locator("[data-turn-np-index]").nth(0)
    playwright.expect(slot).to_have_value("2")
    slot.focus()
    pending.pop().fulfill(json={"strategies": [{"name": "Preset", "path": "strategy/Preset.json"}]})
    playwright.expect(page.locator("#preset-strategy-source")).to_have_value("Preset")
    playwright.expect(slot).to_be_focused()
    page.close()
