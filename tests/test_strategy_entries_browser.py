import json
import os

import pytest

playwright = pytest.importorskip("playwright.sync_api")
from tests.test_assist_tags_browser import tag_console

pytestmark = pytest.mark.skipif(
    not os.environ.get("BBCHANNEL_TEST_CHROMIUM"),
    reason="Set BBCHANNEL_TEST_CHROMIUM to a local Chromium executable.",
)


def _rename(page, name):
    field = page.locator("#preset-strategy-tag")
    field.fill(name)
    field.press("Tab")


def _entries(page):
    return json.loads(page.locator("#preset-json").input_value())


@pytest.mark.parametrize("width,height", [(1440, 1000), (390, 844)])
def test_create_manage_and_save_strategy_without_editing_json(tag_console, width, height):
    browser, url, directory = tag_console
    page = browser.new_page(viewport={"width": width, "height": height})
    page.set_default_timeout(10000)
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(url)
    page.locator("#new-strategy").click()
    playwright.expect(page.locator("#preset-strategy-tag")).to_have_value("Entry 1")
    playwright.expect(page.locator("#move-strategy-entry-up")).to_be_disabled()
    playwright.expect(page.locator("#move-strategy-entry-down")).to_be_disabled()
    page.locator("#preset-name").fill("Visual")
    _rename(page, "Opening")
    first_card = page.locator('[data-strategy-card="card1"]')
    first_card.locator('[data-card-field="type"]').select_option("0")
    first_card.locator('[data-card-field="cards"]').fill("2, 1")
    first_card.locator('[data-card-field="cards"]').press("Tab")
    page.locator("#add-strategy-entry").click()
    playwright.expect(page.locator("#preset-strategy-entry")).to_have_value("1")
    _rename(page, "Second")
    page.locator("#duplicate-strategy-entry").click()
    playwright.expect(page.locator("#preset-strategy-tag")).to_have_value("Second Copy")
    _rename(page, "Third")
    page.locator("#move-strategy-entry-up").click()
    assert [entry["tag"] for entry in _entries(page)] == ["Opening", "Third", "Second"]
    playwright.expect(page.locator("#preset-strategy-entry")).to_have_value("1")
    page.locator("#move-strategy-entry-up").click()
    playwright.expect(page.locator("#move-strategy-entry-up")).to_be_disabled()
    page.locator("#move-strategy-entry-down").click()
    page.once("dialog", lambda dialog: dialog.accept())
    page.locator("#delete-strategy-entry").click()
    assert [entry["tag"] for entry in _entries(page)] == ["Opening", "Second"]
    playwright.expect(page.locator("#preset-strategy-tag")).to_have_value("Second")
    playwright.expect(page.locator("#move-strategy-entry-down")).to_be_disabled()
    page.locator(".preset-form").evaluate("element => element.scrollTop = 0")
    page.screenshot(path=str(directory / f"strategy-entries-{width}.png"))
    assert page.locator("#preset-dialog").evaluate("e => e.scrollWidth <= e.clientWidth")
    assert page.locator(".preset-form").evaluate("e => e.scrollWidth <= e.clientWidth")
    assert page.locator(".strategy-entry-actions img").evaluate_all(
        "images => images.length === 5 && images.every(image => image.complete && image.naturalWidth > 0)"
    )
    page.locator("#save-preset").click()
    playwright.expect(page.locator("#preset-dialog")).not_to_be_visible()
    entries = page.request.get(f"{url}/api/strategies/Visual").json()["entries"]
    assert [entry["tag"] for entry in entries] == ["Opening", "Second"]
    assert entries[0]["strategy"]["card1"]["cards"] == [2, 1]
    assert entries[1]["strategy"]["card1"]["type"] == 2
    assert errors == []
    page.close()


def test_entry_operations_preserve_unknown_fields_and_invalid_drafts(tag_console):
    browser, url, _directory = tag_console
    page = browser.new_page()
    page.set_default_timeout(10000)
    spec = {"type": 1, "cards": ["1B"], "criticalStar": 0, "more_or_less": True, "unknown": [1, 2]}
    rule = {**{f"card{i}": spec for i in (1, 2, 3)}, "breakpoint": [False, False], "colorFirst": True, "custom": {"v": 4}}
    original = [{"tag": name, "strategy": rule, "metadata": {"id": index}} for index, name in enumerate(("First", "Second"))]
    assert page.request.put(f"{url}/api/strategies/entries", data={"entries": original}).ok
    page.goto(url)
    page.locator("#strategy-select").select_option("entries")
    page.locator("#edit-strategy").click()
    field = page.locator('[data-strategy-card="card2"] [data-card-field="cards"]')
    field.fill("4X")
    field.press("Tab")
    _rename(page, "")
    page.locator("#move-strategy-entry-down").click()
    playwright.expect(field).to_have_value("4X")
    playwright.expect(page.locator("#preset-strategy-tag")).to_have_value("")
    assert not field.evaluate("e => e.checkValidity()")
    assert not page.locator("#preset-strategy-tag").evaluate("e => e.checkValidity()")
    page.locator("#duplicate-strategy-entry").click()
    playwright.expect(field).to_have_value("4X")
    playwright.expect(page.locator("#preset-strategy-tag")).to_have_value("")
    _rename(page, "Copy")
    field.fill("2A")
    field.press("Tab")
    page.locator("#save-preset").click()
    playwright.expect(page.locator("#preset-strategy-entry")).to_have_value("1")
    playwright.expect(field).to_have_value("4X")
    assert page.request.get(f"{url}/api/strategies/entries").json()["entries"] == original
    page.once("dialog", lambda dialog: dialog.accept())
    page.locator("#delete-strategy-entry").click()
    playwright.expect(page.locator("#preset-strategy-tag")).to_have_value("Copy")
    result = _entries(page)
    assert result[0] == original[1]
    assert result[1]["metadata"] == original[0]["metadata"]
    assert result[1]["strategy"]["custom"] == {"v": 4}
    assert result[1]["strategy"]["card2"] == {**spec, "cards": ["2A"]}
    page.locator("#save-preset").click()
    playwright.expect(page.locator("#preset-dialog")).not_to_be_visible()
    assert page.request.get(f"{url}/api/strategies/entries").json()["entries"] == result
    page.close()


def test_empty_entries_can_be_rebuilt_but_invalid_json_cannot_be_overwritten(tag_console):
    browser, url, _directory = tag_console
    page = browser.new_page()
    page.set_default_timeout(10000)
    page.goto(url)
    page.locator("#new-strategy").click()
    page.once("dialog", lambda dialog: dialog.accept())
    page.locator("#delete-strategy-entry").click()
    assert _entries(page) == []
    assert page.locator("#preset-strategy-entry").evaluate("e => e.selectedOptions[0]?.textContent") == "No strategy entries"
    playwright.expect(page.locator("#add-strategy-entry")).to_be_enabled()
    playwright.expect(page.locator("#duplicate-strategy-entry")).to_be_disabled()
    playwright.expect(page.locator("#delete-strategy-entry")).to_be_disabled()
    playwright.expect(page.locator("#preset-strategy-tag")).to_be_disabled()
    page.locator("#add-strategy-entry").click()
    playwright.expect(page.locator("#preset-strategy-tag")).to_have_value("Entry 1")
    page.locator("#preset-json").fill("{")
    playwright.expect(page.locator("#add-strategy-entry")).to_be_disabled()
    assert page.locator("#preset-json").input_value() == "{"
    page.locator("#preset-json").fill("[null]")
    playwright.expect(page.locator("#add-strategy-entry")).to_be_enabled()
    playwright.expect(page.locator("#duplicate-strategy-entry")).to_be_disabled()
    page.once("dialog", lambda dialog: dialog.accept())
    page.locator("#delete-strategy-entry").click()
    page.locator("#add-strategy-entry").click()
    playwright.expect(page.locator("#preset-strategy-tag")).to_have_value("Entry 1")
    page.close()


def test_cancel_delete_preserves_draft_and_raw_json_can_repair_entry_name(tag_console):
    browser, url, _directory = tag_console
    page = browser.new_page()
    page.set_default_timeout(10000)
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(url)
    page.locator("#new-strategy").click()
    original = page.locator("#preset-json").input_value()
    _rename(page, "")
    page.once("dialog", lambda dialog: dialog.dismiss())
    page.locator("#delete-strategy-entry").click()
    assert page.locator("#preset-json").input_value() == original
    playwright.expect(page.locator("#preset-strategy-tag")).to_have_value("")
    assert not page.locator("#preset-strategy-tag").evaluate("e => e.checkValidity()")
    entries = _entries(page)
    entries[0]["tag"] = {"toString": None}
    source = json.dumps(entries)
    page.locator("#preset-json").fill(source)
    assert page.locator("#preset-json").input_value() == source
    playwright.expect(page.locator("#preset-strategy-entry option")).to_have_text("1. Untitled")
    _rename(page, "Recovered")
    page.locator("#preset-name").fill("RecoveredPreset")
    page.locator("#save-preset").click()
    playwright.expect(page.locator("#preset-dialog")).not_to_be_visible()
    assert page.request.get(f"{url}/api/strategies/RecoveredPreset").json()["entries"][0]["tag"] == "Recovered"
    page.locator("#new-strategy").click()
    _rename(page, "")
    page.locator("#cancel-preset").click()
    page.locator("#new-setting").click()
    page.locator("#preset-name").fill("NewScript")
    page.locator("#save-preset").click()
    playwright.expect(page.locator("#preset-dialog")).not_to_be_visible()
    assert page.request.get(f"{url}/api/settings/NewScript").ok
    assert errors == []
    page.close()
