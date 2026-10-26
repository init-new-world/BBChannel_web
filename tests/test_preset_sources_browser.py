import json
import os
from pathlib import Path

import pytest

playwright = pytest.importorskip("playwright.sync_api")
from tests.test_api import _strategy_payload
from tests.test_assist_tags_browser import tag_console

pytestmark = pytest.mark.skipif(not os.environ.get("BBCHANNEL_TEST_CHROMIUM"), reason="Set BBCHANNEL_TEST_CHROMIUM.")


def _source(kind):
    extension = {"integer": 9007199254740993, "float": 1.0}
    value = {"server": "CH", "round1_turns": 1, "round1_turn0_skill": [1.0], "extension": extension} if kind == "settings" else [
        {"tag": "Typed", "strategy": _strategy_payload(), "extension": extension},
    ]
    return "\n" + json.dumps(value, indent=3) + "\n"


def _write(directory, kind):
    target = directory / "data" / ("settings" if kind == "settings" else "strategy")
    target.mkdir(exist_ok=True)
    source = _source(kind)
    (target / "Typed.json").write_text(source)
    return source


def _assert_types(path, kind):
    value = json.loads(path.read_text())
    extension = value["extension"] if kind == "settings" else value[0]["extension"]
    assert type(extension["float"]) is float
    assert extension["integer"] == 9007199254740993
    assert type(extension["integer"]) is int
    if kind == "settings":
        assert type(value["round1_turn0_skill"][0]) is float


@pytest.mark.parametrize("kind,picker,button", [("settings", "setting", "setting"), ("strategies", "strategy", "strategy")])
@pytest.mark.parametrize("mode", ["edit", "duplicate"])
def test_editing_or_copying_without_changes_keeps_numeric_source_types(tag_console, kind, picker, button, mode):
    browser, url, directory = tag_console
    source = _write(directory, kind)
    page = browser.new_page()
    page.goto(url)
    page.locator(f"#{picker}-select").select_option("Typed")
    page.locator(f"#{mode}-{button}").click()
    playwright.expect(page.locator("#preset-dialog")).to_be_visible()
    playwright.expect(page.locator("#preset-json")).to_have_value(source)
    name = "Typed"
    if mode == "duplicate":
        name = "TypedCopy"
        page.locator("#preset-name").fill(name)
    page.locator("#save-preset").click()
    playwright.expect(page.locator("#preset-dialog")).not_to_be_visible()
    folder = "settings" if kind == "settings" else "strategy"
    _assert_types(directory / "data" / folder / f"{name}.json", kind)
    _assert_types(directory / "data" / folder / "Typed.json", kind)
    page.close()


def test_imported_script_and_manual_json_save_preserve_numeric_source_types(tag_console):
    browser, url, directory = tag_console
    page = browser.new_page()
    page.goto(url)
    source = _source("settings")
    page.locator("#setting-file-input").set_input_files({"name": "Typed.json", "mimeType": "application/json", "buffer": source.encode()})
    playwright.expect(page.locator("#preset-dialog")).to_be_visible()
    playwright.expect(page.locator("#preset-json")).to_have_value(source)
    page.locator("#save-preset").click()
    playwright.expect(page.locator("#preset-dialog")).not_to_be_visible()
    _assert_types(directory / "data" / "settings" / "Typed.json", "settings")
    page.locator("#new-setting").click()
    page.locator("#preset-name").fill("Manual")
    page.locator("#preset-json").fill(source)
    page.locator("#save-preset").click()
    playwright.expect(page.locator("#preset-dialog")).not_to_be_visible()
    _assert_types(directory / "data" / "settings" / "Manual.json", "settings")
    page.close()


def test_export_uses_the_script_source_instead_of_a_javascript_round_trip(tag_console):
    browser, url, directory = tag_console
    source = _write(directory, "settings")
    page = browser.new_page()
    page.goto(url)
    page.locator("#setting-select").select_option("Typed")
    with page.expect_download() as download:
        page.locator("#export-setting").click()
    assert download.value.suggested_filename == "Typed.json"
    assert Path(download.value.path()).read_text() == source
    page.close()


def test_editor_can_still_read_detail_responses_without_the_optional_source(tag_console):
    browser, url, _directory = tag_console
    page = browser.new_page()
    config = {"server": "CH", "round1_turns": 0, "extension": {"keep": True}}
    page.route("**/api/settings/demo", lambda route: route.fulfill(json={"config": config}))
    page.goto(url)
    page.locator("#edit-setting").click()
    playwright.expect(page.locator("#preset-dialog")).to_be_visible()
    assert json.loads(page.locator("#preset-json").input_value()) == config
    page.close()
