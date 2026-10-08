import os

import pytest

playwright = pytest.importorskip("playwright.sync_api")
from tests.test_assist_tags_browser import tag_console

pytestmark = pytest.mark.skipif(
    not os.environ.get("BBCHANNEL_TEST_CHROMIUM"),
    reason="Set BBCHANNEL_TEST_CHROMIUM to a local Chromium executable.",
)


@pytest.mark.parametrize("width,height,max_header,max_run", [
    (390, 844, 180, 205),
    (320, 720, 180, 230),
])
def test_mobile_header_and_run_options_are_compact(tag_console, width, height, max_header, max_run):
    browser, url, directory = tag_console
    page = browser.new_page(viewport={"width": width, "height": height})
    page.set_default_timeout(10000)
    page.goto(url)
    header = page.locator(".topbar")
    assert header.evaluate("e => e.getBoundingClientRect().height") <= max_header
    assert header.evaluate("e => e.scrollWidth <= e.clientWidth")
    connect = page.locator("#connect-device").bounding_box()
    disconnect = page.locator("#disconnect-device").bounding_box()
    assert abs(connect["y"] - disconnect["y"]) <= 1
    page.locator("#edit-setting").click()
    page.locator("#preset-run-options summary").click()
    run = page.locator("#preset-run-options")
    assert run.evaluate("e => e.getBoundingClientRect().height") <= max_run
    assert page.locator(".preset-form").evaluate("e => e.scrollWidth <= e.clientWidth")
    page.screenshot(path=str(directory / f"compact-layout-{width}.png"))
    page.close()
