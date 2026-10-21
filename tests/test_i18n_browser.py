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


@pytest.mark.parametrize("width,height", [(1440, 1000), (390, 844)])
def test_team_editor_translates_generated_ui_without_translating_catalog_names(tag_console, width, height):
    browser, url, directory = tag_console
    (directory / "data" / "servant_info_CH.json").write_text(json.dumps({
        "Support": {"SN": "314"}, "None": {"SN": "999"},
    }))
    (directory / "data" / "master_info.json").write_text(json.dumps({"None": {"SN": 7}}))
    page = browser.new_page(viewport={"width": width, "height": height})
    original = {"server": "CH", "round1_turns": 0, "custom": {"keep": True}}
    assert page.request.put(f"{url}/api/settings/demo", data={"config": original, "overwrite": True}).ok
    page.goto(url)
    page.locator("#language-select").select_option("zh-CN")
    page.locator("#edit-setting").click()
    draft = {**original, "servant_0_name": "Legacy", "master_equip": 42,
             "usedServant": [0, "legacy"]}
    page.locator("#preset-json").fill(json.dumps(draft))
    page.locator("#preset-team summary").click()
    playwright.expect(page.locator("#preset-team-status")).to_have_text("2 位从者 (CH)")
    playwright.expect(page.locator("#preset-master-status")).to_have_text("1 套御主礼装")
    playwright.expect(page.locator('[data-team-slot="0"] option').first).to_have_text("无")
    playwright.expect(page.locator('[data-team-slot="0"] option[value="None"]')).to_have_text("None")
    playwright.expect(page.locator('[data-team-slot="0"] option:checked')).to_have_text("Legacy（当前）")
    playwright.expect(page.locator("#preset-master-equip option[value='']").first).to_have_text("无")
    playwright.expect(page.locator("#preset-master-equip option[value='7']")).to_have_text("None")
    playwright.expect(page.locator("#preset-master-equip option:checked")).to_have_text("42（当前）")
    playwright.expect(page.locator("#preset-assist-slot option").first).to_have_text("未设置")
    playwright.expect(page.locator("#preset-assist-slot option[value='0']")).to_have_text("第 1 位")
    playwright.expect(page.locator("#preset-used-status")).to_have_text("已保留无法识别的条目。")
    assert json.loads(page.locator("#preset-json").input_value()) == draft
    page.locator('[data-team-slot="0"]').select_option("None")
    page.locator("#preset-master-equip").select_option("7")
    assert json.loads(page.locator("#preset-json").input_value()) == {
        **draft, "servant_0_name": "None", "master_equip": 7,
    }
    assert page.request.get(f"{url}/api/settings/demo").json()["config"] == original
    page.locator("#preset-team").scroll_into_view_if_needed()
    page.screenshot(path=str(directory / f"i18n-team-{width}.png"))
    assert page.locator(".preset-form").evaluate("e => e.scrollWidth <= e.clientWidth")
    page.close()


def test_team_editor_translates_local_validation_but_keeps_backend_errors_verbatim(tag_console):
    browser, url, _directory = tag_console
    page = browser.new_page(locale="zh-CN")
    page.route("**/api/servants?*", lambda route: route.fulfill(
        status=503, json={"error": {"message": "Catalog offline"}},
    ))
    page.goto(url)
    page.locator("#new-setting").click()
    page.locator("#preset-team summary").click()
    playwright.expect(page.locator("#preset-team-status")).to_have_text("Catalog offline")
    page.locator("#preset-json").fill(json.dumps({"server": "unsupported", "usedServant": {"future": 1}}))
    playwright.expect(page.locator("#preset-team-status")).to_have_text("不支持的服务器。")
    playwright.expect(page.locator("#preset-used-status")).to_have_text("usedServant 值无效。")
    page.locator("#preset-json").fill("{")
    playwright.expect(page.locator("#preset-team-status")).to_have_text("脚本 JSON 无效。")
    playwright.expect(page.locator("#preset-master-status")).to_have_text("脚本 JSON 无效。")
    page.close()
