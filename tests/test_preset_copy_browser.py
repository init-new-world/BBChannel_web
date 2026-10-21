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


@pytest.mark.parametrize("width,height", [(1440, 1000), (390, 844)])
@pytest.mark.parametrize("kind,subject,source,copy_name", [
    ("settings", "Script", "demo", "CopiedScript"),
    ("strategies", "Strategy", "Preset", "CopiedStrategy"),
])
def test_copy_preset_is_an_independent_draft_with_name_conflict_protection(
    tag_console, width, height, kind, subject, source, copy_name,
):
    browser, url, directory = tag_console
    page = browser.new_page(viewport={"width": width, "height": height})
    entries, config = _seed(page, url)
    original = config if kind == "settings" else entries
    field = "config" if kind == "settings" else "entries"
    control = "setting" if kind == "settings" else "strategy"
    page.goto(url)
    button = page.locator(f"#duplicate-{control}")
    playwright.expect(button).to_be_enabled()
    page.screenshot(path=str(directory / f"copy-toolbar-{kind}-{width}.png"))
    button.click()
    playwright.expect(page.locator("#preset-dialog-title")).to_have_text(f"Duplicate {subject}")
    playwright.expect(page.locator("#preset-name")).to_have_value("")
    playwright.expect(page.locator("#preset-name")).to_be_focused()
    assert _config(page) == original
    page.screenshot(path=str(directory / f"copy-preset-{kind}-{width}.png"))
    assert page.locator(".preset-form").evaluate("e => e.scrollWidth <= e.clientWidth")
    page.locator("#preset-name").fill(source)
    page.locator("#save-preset").click()
    playwright.expect(page.locator("#preset-error")).to_contain_text("already exists")
    playwright.expect(page.locator("#preset-dialog")).to_be_visible()
    assert page.request.get(f"{url}/api/{kind}/{source}").json()[field] == original
    expected = {**config, "custom": {"copied": True}} if kind == "settings" else [
        {**entries[0], "tag": "Copied first"}, *entries[1:],
    ]
    page.locator("#preset-json").fill(json.dumps(expected))
    page.locator("#preset-name").fill(copy_name)
    page.locator("#save-preset").click()
    playwright.expect(page.locator("#preset-dialog")).not_to_be_visible()
    playwright.expect(page.locator(f"#{control}-select")).to_have_value(copy_name)
    assert page.request.get(f"{url}/api/{kind}/{copy_name}").json()[field] == expected
    assert page.request.get(f"{url}/api/{kind}/{source}").json()[field] == original
    page.close()


def test_late_copy_response_cannot_replace_a_new_editor_draft(tag_console):
    browser, url, _directory = tag_console
    page = browser.new_page()
    entries, _config_value = _seed(page, url)
    page.goto(url)
    playwright.expect(page.locator("#edit-setting")).to_be_enabled()
    source = page.request.get(f"{url}/api/settings/demo")
    pending = []
    page.route("**/api/settings/demo", lambda route: pending.append(route))
    page.locator("#duplicate-setting").click()
    assert len(pending) == 1
    page.locator("#new-strategy").click()
    page.locator("#preset-json").fill(json.dumps(entries))
    with page.expect_response(f"{url}/api/settings/demo") as response:
        pending.pop().fulfill(response=source)
    response.value.finished()
    playwright.expect(page.locator("#preset-dialog-title")).to_have_text("New Strategy")
    assert _config(page) == entries
    page.locator("#cancel-preset").click()
    assert len(page.request.get(f"{url}/api/settings").json()["settings"]) == 1
    page.close()


def test_copy_controls_follow_selection_and_localized_labels(tag_console):
    browser, url, _directory = tag_console
    page = browser.new_page(locale="zh-CN")
    page.goto(url)
    playwright.expect(page.locator("#duplicate-strategy")).to_be_disabled()
    copy = page.locator("#duplicate-setting")
    playwright.expect(copy).to_have_attribute("title", "复制脚本")
    copy.click()
    playwright.expect(page.locator("#preset-dialog-title")).to_have_text("复制脚本")
    page.locator("#cancel-preset").click()
    original = page.request.get(f"{url}/api/settings/demo").json()["config"]
    page.locator("#setting-file-input").set_input_files({
        "name": "Imported.json", "mimeType": "application/json", "buffer": json.dumps(original).encode(),
    })
    playwright.expect(page.locator("#preset-dialog-title")).to_have_text("导入脚本")
    assert _config(page) == original
    playwright.expect(page.locator("#setting-file-input")).to_have_value("")
    page.locator("#cancel-preset").click()
    assert page.request.delete(f"{url}/api/settings/demo").ok
    page.locator("#refresh-settings").click()
    playwright.expect(copy).to_be_disabled()
    page.close()
