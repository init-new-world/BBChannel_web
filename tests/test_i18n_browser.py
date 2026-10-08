import json
import os

import pytest

playwright = pytest.importorskip("playwright.sync_api")
from tests.test_assist_tags_browser import tag_console

pytestmark = pytest.mark.skipif(
    not os.environ.get("BBCHANNEL_TEST_CHROMIUM"),
    reason="Set BBCHANNEL_TEST_CHROMIUM to a local Chromium executable.",
)


@pytest.mark.parametrize("width,height", [(1440, 1000), (390, 844), (320, 720)])
def test_language_menu_translates_console_and_persists_without_changing_script(tag_console, width, height):
    browser, url, directory = tag_console
    page = browser.new_page(viewport={"width": width, "height": height}, locale="en-US")
    page.set_default_timeout(10000)
    original = page.request.get(f"{url}/api/settings/demo").json()["config"]
    page.goto(url)
    language = page.locator("#language-select")
    playwright.expect(language).to_be_visible()
    playwright.expect(language).to_have_value("en")
    playwright.expect(page.locator("#connection-state")).to_contain_text("fixture")
    connection = page.locator("#connection-state").inner_text()
    language.select_option("zh-CN")
    playwright.expect(page.locator("html")).to_have_attribute("lang", "zh-CN")
    playwright.expect(language).to_have_attribute("aria-label", "语言")
    playwright.expect(page.locator("#new-setting")).to_have_text("新建")
    playwright.expect(page.locator("#start-full-run")).to_have_text("开始完整运行")
    playwright.expect(page.locator("#setting-validation")).to_contain_text("有效")
    assert page.locator("#connection-state").inner_text() == connection
    assert page.evaluate("localStorage.getItem('bbchannel.locale')") == "zh-CN"
    assert page.request.get(f"{url}/api/settings/demo").json()["config"] == original
    page.reload()
    playwright.expect(language).to_have_value("zh-CN")
    playwright.expect(page.locator("#new-setting")).to_have_text("新建")
    playwright.expect(page.locator("#refresh-settings span")).to_have_text("刷新脚本")
    assert page.locator(".topbar").evaluate("e => e.scrollWidth <= e.clientWidth")
    page.screenshot(path=str(directory / f"i18n-header-{width}.png"))
    page.locator("#edit-setting").click()
    playwright.expect(page.locator("#preset-dialog-title")).to_have_text("编辑脚本")
    playwright.expect(page.locator("#preset-run-options summary")).to_have_text("运行选项")
    playwright.expect(page.locator("#preset-wave-list")).to_contain_text("第 1 波")
    playwright.expect(page.locator("#preset-wave-list")).to_contain_text("0 回合")
    playwright.expect(page.locator("#preset-strategy-target option")).to_have_text("未配置回合")
    playwright.expect(page.locator("#preset-strategy-source option")).to_have_text("无可用预设")
    assert json.loads(page.locator("#preset-json").input_value()) == original
    page.screenshot(path=str(directory / f"i18n-{width}.png"))
    assert page.locator("#preset-dialog").evaluate("e => e.scrollWidth <= e.clientWidth")
    page.locator("#cancel-preset").click()
    language.select_option("en")
    playwright.expect(page.locator("#new-setting")).to_have_text("New")
    playwright.expect(page.locator("html")).to_have_attribute("lang", "en")
    playwright.expect(language).to_have_attribute("aria-label", "Language")
    assert page.locator(".topbar").evaluate("e => e.scrollWidth <= e.clientWidth")
    if width <= 390:
        assert page.locator(".topbar").evaluate("e => e.getBoundingClientRect().height") <= 180
    page.close()


def test_language_menu_fits_all_header_breakpoints(tag_console):
    browser, url, _directory = tag_console
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    page.goto(url)
    page.locator("#language-select").select_option("zh-CN")
    for width in (1440, 1251, 1250, 901, 900, 561, 560, 390, 360, 320):
        page.set_viewport_size({"width": width, "height": 900})
        assert page.locator(".topbar").evaluate("e => e.scrollWidth <= e.clientWidth"), width
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), width
    page.close()


def test_browser_language_is_used_without_saved_preference_and_invalid_saved_value_is_ignored(tag_console):
    browser, url, _directory = tag_console
    page = browser.new_page(locale="zh-CN")
    page.goto(url)
    playwright.expect(page.locator("#language-select")).to_have_value("zh-CN")
    playwright.expect(page.locator("#new-setting")).to_have_text("新建")
    page.evaluate("localStorage.setItem('bbchannel.locale', 'invalid')")
    page.reload()
    playwright.expect(page.locator("#language-select")).to_have_value("zh-CN")
    page.close()
