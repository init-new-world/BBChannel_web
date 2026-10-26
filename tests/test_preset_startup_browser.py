import os

import pytest

playwright = pytest.importorskip("playwright.sync_api")
from tests.test_assist_tags_browser import tag_console
from tests.test_strategy_assignment_browser import _seed

pytestmark = pytest.mark.skipif(not os.environ.get("BBCHANNEL_TEST_CHROMIUM"), reason="Set BBCHANNEL_TEST_CHROMIUM.")


@pytest.mark.parametrize("fail", [False, True])
def test_preset_actions_are_disabled_until_startup_has_a_selected_preset(tag_console, fail):
    browser, url, _directory = tag_console
    page = browser.new_page()
    _seed(page, url)
    pending = []
    startup = {"released": False}

    def handle(route):
        if not startup["released"]:
            pending.append(route)
        elif fail:
            route.fulfill(status=503, json={"error": {"message": "Startup unavailable"}})
        else:
            route.continue_()

    page.route("**/api/**", handle)
    page.goto(url)
    buttons = [page.locator(f"#{name}") for name in (
        "edit-setting", "duplicate-setting", "delete-setting", "export-setting",
        "edit-strategy", "duplicate-strategy", "delete-strategy",
    )]
    for button in buttons:
        playwright.expect(button).to_be_disabled(timeout=1000)
    playwright.expect(page.locator("#preset-dialog")).not_to_be_visible()
    playwright.expect(page.locator("#new-setting")).to_be_enabled()
    playwright.expect(page.locator("#new-strategy")).to_be_enabled()
    startup["released"] = True
    for route in pending:
        if fail:
            route.fulfill(status=503, json={"error": {"message": "Startup unavailable"}})
        else:
            route.continue_()
    page.unroute("**/api/**")
    if fail:
        playwright.expect(page.locator("#setting-validation")).to_have_text("Settings unavailable")
        for button in buttons:
            playwright.expect(button).to_be_disabled()
    else:
        playwright.expect(page.locator("#setting-select")).to_have_value("demo")
        playwright.expect(page.locator("#strategy-select")).to_have_value("Preset")
        for button in buttons:
            playwright.expect(button).to_be_enabled()
        page.locator("#edit-setting").click()
        playwright.expect(page.locator("#preset-dialog")).to_be_visible()
        source = '{"server":"CH","round1_turns":1000000000}'
        page.locator("#preset-json").fill(source)
        playwright.expect(page.locator("#preset-turn-strategy-status")).to_have_text("Turn list exceeds 1,000 entries.")
        assert page.locator("#preset-json").input_value() == source
    page.close()
