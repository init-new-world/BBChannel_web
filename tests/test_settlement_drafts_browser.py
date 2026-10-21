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


@pytest.mark.parametrize("initial", [None, "13", [1, 3]])
def test_pending_strategy_list_does_not_discard_focused_settlement_text(tag_console, initial):
    browser, url, _directory = tag_console
    page = browser.new_page()
    _seed(page, url)
    strategy_response = page.request.get(f"{url}/api/strategies")
    pending = []
    page.route("**/api/strategies", lambda route: pending.append(route))
    page.goto(url)
    page.locator("#new-setting").click()
    page.locator("#preset-name").fill("SettlementDraft")
    raw = {"server": "CH", "round1_turns": 1, "custom": [1, 2]}
    if initial is not None:
        raw["ignoreFriendship"] = initial
    page.locator("#preset-json").fill(json.dumps(raw))
    page.locator("#preset-settlement summary").click()
    ignored = page.locator('[data-settlement-option="ignoreFriendship"]')
    ignored.fill("245")
    playwright.expect(ignored).to_be_focused()
    assert len(pending) == 1
    pending.pop().fulfill(response=strategy_response)
    playwright.expect(page.locator("#preset-strategy-source option[value='Preset']")).to_be_attached()
    playwright.expect(ignored).to_be_focused()
    playwright.expect(ignored).to_have_value("245", timeout=2000)
    assert _config(page) == {**raw, "ignoreFriendship": "245"}
    page.locator("#save-preset").click()
    playwright.expect(page.locator("#preset-dialog")).not_to_be_visible()
    assert page.request.get(f"{url}/api/settings/SettlementDraft").json()["config"] == {**raw, "ignoreFriendship": "245"}
    page.close()
