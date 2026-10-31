import json
import os

import pytest

playwright = pytest.importorskip("playwright.sync_api")
from tests.test_assist_tags_browser import tag_console
from tests.test_assist_sources_browser import _legacy
from tests.test_settlement_options_browser import _option
from tests.test_strategy_assignment_browser import _config, _seed

pytestmark = pytest.mark.skipif(not os.environ.get("BBCHANNEL_TEST_CHROMIUM"), reason="Set BBCHANNEL_TEST_CHROMIUM.")
FIELDS = ("fullFriendshipStop", "ignoreFriendship", "addFriend")


def _open(page, url, directory):
    _entries, original = _seed(page, url)
    original.update({"metadata": {"float": 1.0, "large": 9007199254740993},
                     "round1_turn0_skill": [1.0, [1, 2.0]], "fullFriendshipStop": False,
                     "ignoreFriendship": "x1,3", "addFriend": False})
    path = directory / "data" / "settings" / "demo.json"
    path.write_text(json.dumps(original))
    page.goto(url)
    page.locator("#edit-setting").click()
    page.locator("#preset-settlement summary").click()
    return original, path


@pytest.mark.parametrize("width,locale", [(1440, "en-US"), (390, "zh-CN"), (320, "en-US")])
def test_settlement_edits_preserve_other_source_and_saved_unsupported_skill_types(tag_console, width, locale):
    browser, url, directory = tag_console
    page = browser.new_page(viewport={"width": width, "height": 900}, locale=locale)
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    original, path = _open(page, url, directory)
    before = path.read_bytes()
    _option(page, "fullFriendshipStop").check()
    _legacy(page)
    _option(page, "ignoreFriendship").fill(" x2,4;5 ")
    _legacy(page)
    _option(page, "addFriend").check()
    _legacy(page)
    expected = {**original, "fullFriendshipStop": True, "ignoreFriendship": " x2,4;5 ", "addFriend": True}
    assert _config(page) == expected
    assert path.read_bytes() == before
    page.locator("#preset-settlement").scroll_into_view_if_needed()
    page.screenshot(path=str(directory / f"settlement-source-{width}.png"))
    assert page.locator(".preset-form").evaluate("e => e.scrollWidth <= e.clientWidth")
    page.locator("#save-preset").click()
    playwright.expect(page.locator("#preset-dialog")).not_to_be_visible()
    saved = json.loads(path.read_text())
    assert saved == expected
    assert type(saved["metadata"]["float"]) is float
    assert saved["metadata"]["large"] == 9007199254740993
    assert type(saved["round1_turn0_skill"][0]) is float
    assert type(saved["round1_turn0_skill"][1][1]) is float
    plan = page.request.get(f"{url}/api/settings/demo/plan").json()["run"]
    assert plan["full_friendship_stop"] is True
    assert plan["ignored_friendship_slots"] == [2, 4, 5]
    assert plan["add_friend"] is True
    assert page.request.get(f"{url}/api/settings/demo/program").json()["summary"]["unsupported_action_count"] == 2
    assert errors == []
    page.close()


@pytest.mark.parametrize("field", FIELDS)
def test_duplicate_settlement_fields_lock_only_the_target_until_raw_correction(tag_console, field):
    browser, url, directory = tag_console
    page = browser.new_page(locale="zh-CN")
    original, _path = _open(page, url, directory)
    alias = f"\\u{ord(field[0]):04x}" + field[1:]
    source = json.dumps(original)[:-1] + ',"' + alias + '":' + json.dumps(original[field]) + '}'
    page.locator("#preset-json").fill(source)
    playwright.expect(_option(page, field)).to_be_disabled()
    playwright.expect(_option(page, field)).to_have_attribute("title", "结算字段含义不明确。")
    event = "input" if field == "ignoreFriendship" else "change"
    _option(page, field).evaluate(f"e => e.dispatchEvent(new Event('{event}',{{bubbles:true}}))")
    assert page.locator("#preset-json").input_value() == source
    other = "addFriend" if field != "addFriend" else "fullFriendshipStop"
    playwright.expect(_option(page, other)).to_be_enabled()
    _option(page, other).check()
    changed = page.locator("#preset-json").input_value()
    assert [value for name, value in json.loads(changed, object_pairs_hook=list) if name == field] == [original[field], original[field]]
    _legacy(page)
    page.locator("#preset-json").fill(json.dumps(original))
    playwright.expect(_option(page, field)).to_be_enabled()
    assert _option(page, field).get_attribute("title") != "结算字段含义不明确。"
    if field == "ignoreFriendship":
        _option(page, field).fill("")
    else:
        _option(page, field).check()
    _legacy(page)
    page.close()


@pytest.mark.parametrize("operation", ["apply", "save"])
def test_settlement_source_mutations_remain_locked_during_pending_operations(tag_console, operation):
    browser, url, directory = tag_console
    page = browser.new_page()
    original, _path = _open(page, url, directory)
    pending = []
    if operation == "apply":
        response = page.request.get(f"{url}/api/strategies/Preset")
        page.route("**/api/strategies/Preset", lambda route: pending.append(route))
        page.locator("#apply-turn-strategy").click()
    else:
        page.route("**/api/settings/demo", lambda route: pending.append(route))
        page.locator("#save-preset").click()
    for field in FIELDS:
        playwright.expect(_option(page, field)).to_be_disabled()
    before = page.locator("#preset-json").input_value()
    for field in FIELDS:
        event = "input" if field == "ignoreFriendship" else "change"
        _option(page, field).evaluate(f"""e => {{
            if (e.type === 'checkbox') e.checked = !e.checked;
            else e.value = 'busy mutation must not be written';
            e.dispatchEvent(new Event('{event}',{{bubbles:true}}));
        }}""")
    assert page.locator("#preset-json").input_value() == before
    if operation == "apply":
        pending.pop().fulfill(response=response)
    else:
        pending.pop().fulfill(status=500, json={"error": {"message": "Save failed"}})
    playwright.expect(_option(page, "addFriend")).to_be_enabled()
    assert all(_config(page)[field] == original[field] for field in FIELDS)
    _legacy(page)
    page.close()
