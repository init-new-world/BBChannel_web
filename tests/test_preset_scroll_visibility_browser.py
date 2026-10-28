import os

import pytest

playwright = pytest.importorskip("playwright.sync_api")
from tests.test_assist_tags_browser import tag_console
from tests.test_strategy_assignment_browser import _seed

pytestmark = pytest.mark.skipif(not os.environ.get("BBCHANNEL_TEST_CHROMIUM"), reason="Set BBCHANNEL_TEST_CHROMIUM.")


@pytest.mark.parametrize("width,height", [(1440, 900), (390, 900), (320, 640)])
def test_scrolling_to_np_controls_leaves_them_above_the_sticky_actions(tag_console, width, height):
    browser, url, directory = tag_console
    page = browser.new_page(viewport={"width": width, "height": height})
    _seed(page, url)
    page.goto(url)
    page.locator("#edit-setting").click()
    slot = page.locator("[data-turn-np-index]").nth(0)
    playwright.expect(slot).to_have_value("2")
    group = page.locator("#preset-turn-nps")
    group.scroll_into_view_if_needed()
    bounds = group.bounding_box()
    actions = page.locator(".preset-dialog-actions").bounding_box()
    assert bounds["y"] + bounds["height"] <= actions["y"]
    assert slot.evaluate("e => {const r=e.getBoundingClientRect(); return e.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2));}")
    page.screenshot(path=str(directory / f"preset-scroll-{width}.png"))
    page.close()
