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


def _option(page, field):
    return page.locator(f'[data-settlement-option="{field}"]')


@pytest.mark.parametrize("width,height,locale", [(1440, 1000, "en-US"), (390, 844, "zh-CN")])
def test_settlement_options_preserve_original_values_and_update_saved_plan(tag_console, width, height, locale):
    browser, url, directory = tag_console
    page = browser.new_page(viewport={"width": width, "height": height}, locale=locale)
    _entries, original = _seed(page, url)
    original.update({"fullFriendshipStop": 1, "ignoreFriendship": "x1,3", "addFriend": 0})
    assert page.request.put(f"{url}/api/settings/demo", data={"config": original, "overwrite": True}).ok
    page.goto(url)
    page.locator("#edit-setting").click()
    page.locator("#preset-settlement summary").click()
    stop = _option(page, "fullFriendshipStop")
    ignored = _option(page, "ignoreFriendship")
    friend = _option(page, "addFriend")
    playwright.expect(stop).to_be_checked()
    playwright.expect(ignored).to_have_value("x1,3")
    playwright.expect(friend).not_to_be_checked()
    assert _config(page) == original
    stop.uncheck()
    ignored.fill("245")
    ignored.press("Tab")
    friend.check()
    stop.check()
    expected = {**original, "fullFriendshipStop": True, "ignoreFriendship": "245", "addFriend": True}
    assert _config(page) == expected
    assert page.request.get(f"{url}/api/settings/demo").json()["config"] == original
    page.locator("#preset-settlement").scroll_into_view_if_needed()
    page.screenshot(path=str(directory / f"settlement-options-{width}.png"))
    assert page.locator(".preset-form").evaluate("e => e.scrollWidth <= e.clientWidth")
    page.locator("#save-preset").click()
    playwright.expect(page.locator("#preset-dialog")).not_to_be_visible()
    assert page.request.get(f"{url}/api/settings/demo").json()["config"] == expected
    run = page.request.get(f"{url}/api/settings/demo/plan").json()["run"]
    assert run["full_friendship_stop"] is True
    assert run["ignored_friendship_slots"] == [2, 4, 5]
    assert run["add_friend"] is True
    page.close()


@pytest.mark.parametrize("flag", [[], {}, [0], {"enabled": False}, None, "false"])
def test_settlement_controls_keep_legacy_types_until_edited(tag_console, flag):
    browser, url, _directory = tag_console
    page = browser.new_page()
    page.goto(url)
    page.locator("#new-setting").click()
    original = {"server": "CH", "fullFriendshipStop": flag, "addFriend": flag,
                "ignoreFriendship": ["1", 3], "custom": "keep"}
    page.locator("#preset-json").fill(json.dumps(original))
    page.locator("#preset-settlement summary").click()
    assert _option(page, "fullFriendshipStop").is_checked() == bool(flag)
    assert _option(page, "addFriend").is_checked() == bool(flag)
    assert json.loads(_option(page, "ignoreFriendship").input_value()) == ["1", 3]
    assert _config(page) == original
    _option(page, "addFriend").click()
    expected = {**original, "addFriend": not bool(flag)}
    assert _config(page) == expected
    _option(page, "ignoreFriendship").fill("")
    _option(page, "ignoreFriendship").press("Tab")
    assert _config(page) == {**expected, "ignoreFriendship": ""}
    page.close()


def test_settlement_options_lock_during_pending_preset_and_save(tag_console):
    browser, url, _directory = tag_console
    page = browser.new_page()
    _seed(page, url)
    page.goto(url)
    page.locator("#edit-setting").click()
    page.locator("#preset-settlement summary").click()
    pending = []
    page.route("**/api/strategies/Preset", lambda route: pending.append(route))
    response = page.request.get(f"{url}/api/strategies/Preset")
    page.locator("#apply-turn-strategy").click()
    playwright.expect(_option(page, "fullFriendshipStop")).to_be_disabled()
    pending.pop().fulfill(response=response)
    playwright.expect(_option(page, "fullFriendshipStop")).to_be_enabled()
    page.route("**/api/settings/demo", lambda route: pending.append(route))
    page.locator("#save-preset").click()
    playwright.expect(_option(page, "ignoreFriendship")).to_be_disabled()
    pending.pop().fulfill(status=500, json={"error": {"message": "Save failed"}})
    playwright.expect(_option(page, "ignoreFriendship")).to_be_enabled()
    page.close()


def test_settlement_defaults_do_not_change_json_and_invalid_roots_lock_controls(tag_console):
    browser, url, _directory = tag_console
    page = browser.new_page()
    page.goto(url)
    page.locator("#new-setting").click()
    page.locator("#preset-settlement summary").click()
    original = _config(page)
    playwright.expect(_option(page, "fullFriendshipStop")).not_to_be_checked()
    playwright.expect(_option(page, "addFriend")).not_to_be_checked()
    playwright.expect(_option(page, "ignoreFriendship")).to_have_value("")
    assert _config(page) == original
    page.locator("#preset-json").fill("{")
    playwright.expect(_option(page, "addFriend")).to_be_disabled()
    page.locator("#preset-json").fill("[]")
    playwright.expect(_option(page, "ignoreFriendship")).to_be_disabled()
    page.locator("#cancel-preset").click()
    page.locator("#new-strategy").click()
    playwright.expect(page.locator("#preset-settlement")).to_be_hidden()
    page.close()
