import json
import os

import pytest
from PIL import Image, ImageDraw

playwright = pytest.importorskip("playwright.sync_api")
from tests.test_assist_tags_browser import tag_console
from tests.test_strategy_assignment_browser import _config, _seed

pytestmark = pytest.mark.skipif(
    not os.environ.get("BBCHANNEL_TEST_CHROMIUM"),
    reason="Set BBCHANNEL_TEST_CHROMIUM to a local Chromium executable.",
)


def _equips(directory):
    for location, name in [("assist/assist_equip", "First CE"), ("assist/assist_equip", "Second CE"),
                           ("equipmaker/assist_equip_store", "Archived CE")]:
        path = directory / "assets" / location
        path.mkdir(parents=True, exist_ok=True)
        image = Image.new("RGB", (237, 68), (55, 95, 140))
        ImageDraw.Draw(image).text((12, 25), name, fill="white")
        image.save(path / f"{name}.png")


def _row(page, name):
    return page.locator("[data-assist-equip-name]").filter(has=page.get_by_text(name, exact=True))


@pytest.mark.parametrize("width,height", [(1440, 1000), (390, 844)])
def test_edit_equips_uses_active_templates_and_preserves_nested_source(tag_console, width, height):
    browser, url, directory = tag_console
    _equips(directory)
    page = browser.new_page(viewport={"width": width, "height": height})
    page.set_default_timeout(10000)
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    _entries, original = _seed(page, url)
    original.update({"assistMode": "从者礼装", "assistEquip": [["First CE", "Missing CE"], ["First CE"], ""]})
    assert page.request.put(f"{url}/api/settings/demo", data={"config": original, "overwrite": True}).ok
    page.goto(url)
    page.locator("#edit-setting").click()
    page.locator("#preset-assist-equips summary").click()
    source = page.locator("#preset-assist-equip-source")
    playwright.expect(source).to_be_enabled()
    assert source.locator("option").all_text_contents() == ["Second CE"]
    assert _config(page) == original
    playwright.expect(page.locator("[data-assist-equip-name]")).to_have_count(2)
    playwright.expect(_row(page, "Missing CE")).to_contain_text("Unavailable")
    page.wait_for_function("document.querySelector('[data-assist-equip-name] img').naturalWidth === 237")
    page.locator("#add-assist-equip").click()
    expected = {**original, "assistEquip": [["First CE", "Missing CE"], ["First CE"], "", "Second CE"]}
    assert _config(page) == expected
    playwright.expect(page.locator("#add-assist-equip")).to_be_disabled()
    page.locator("#preset-assist-equips").scroll_into_view_if_needed()
    page.screenshot(path=str(directory / f"assist-equips-{width}.png"))
    assert page.locator(".preset-form").evaluate("e => e.scrollWidth <= e.clientWidth")
    _row(page, "First CE").get_by_role("button", name="Remove CE").click()
    expected["assistEquip"] = [["Missing CE"], [], "", "Second CE"]
    assert _config(page) == expected
    playwright.expect(_row(page, "Missing CE").get_by_role("button", name="Remove CE")).to_be_focused()
    assert page.request.get(f"{url}/api/settings/demo").json()["config"] == original
    page.locator("#save-preset").click()
    playwright.expect(page.locator("#preset-dialog")).not_to_be_visible()
    assert page.request.get(f"{url}/api/settings/demo").json()["config"] == expected
    plan = page.request.get(f"{url}/api/settings/demo/plan").json()["assist"]
    assert plan["equip_names"] == ["Missing CE", "Second CE"]
    assert errors == []
    page.close()


@pytest.mark.parametrize("original", ["First CE", None, []])
def test_add_equip_to_legacy_scalar_or_empty_value(tag_console, original):
    browser, url, directory = tag_console
    _equips(directory)
    page = browser.new_page()
    page.goto(url)
    page.locator("#new-setting").click()
    raw = {"server": "CH", "assistEquip": original, "custom": [1, 2]}
    page.locator("#preset-json").fill(json.dumps(raw))
    page.locator("#preset-assist-equips summary").click()
    source = page.locator("#preset-assist-equip-source")
    playwright.expect(source).to_be_enabled()
    source.select_option("Second CE")
    playwright.expect(source).to_have_attribute("title", "Second CE")
    page.locator("#add-assist-equip").click()
    assert _config(page) == {**raw, "assistEquip": (["First CE"] if original else []) + ["Second CE"]}
    page.once("dialog", lambda dialog: dialog.dismiss())
    page.locator("#clear-assist-equips").click()
    assert _config(page)["assistEquip"]
    page.once("dialog", lambda dialog: dialog.accept())
    page.locator("#clear-assist-equips").click()
    assert _config(page) == {**raw, "assistEquip": []}
    page.close()


def test_malformed_equip_value_requires_explicit_clear_and_invalid_json_locks(tag_console):
    browser, url, directory = tag_console
    _equips(directory)
    page = browser.new_page()
    page.goto(url)
    page.locator("#new-setting").click()
    raw = {"server": "CH", "assistEquip": {"future": ["First CE"]}, "custom": "keep"}
    page.locator("#preset-json").fill(json.dumps(raw))
    page.locator("#preset-assist-equips summary").click()
    playwright.expect(page.locator("#preset-assist-equip-status")).to_contain_text("Unsupported CE value")
    playwright.expect(page.locator("#add-assist-equip")).to_be_disabled()
    assert _config(page) == raw
    page.once("dialog", lambda dialog: dialog.accept())
    page.locator("#clear-assist-equips").click()
    playwright.expect(page.locator("#add-assist-equip")).to_be_enabled()
    assert _config(page) == {**raw, "assistEquip": []}
    page.locator("#preset-json").fill("{")
    playwright.expect(page.locator("#add-assist-equip")).to_be_disabled()
    playwright.expect(page.locator("#clear-assist-equips")).to_be_disabled()
    page.close()


def test_inactive_mode_preserves_equips_and_other_control_drafts(tag_console):
    browser, url, directory = tag_console
    _equips(directory)
    page = browser.new_page()
    page.goto(url)
    page.locator("#new-setting").click()
    raw = {"server": "CH", "assistEquip": ["First CE"], "assistMode": "仅从者"}
    page.locator("#preset-json").fill(json.dumps(raw))
    page.locator("#preset-assist-equips summary").click()
    playwright.expect(page.locator("#add-assist-equip")).to_be_disabled()
    playwright.expect(page.locator("#clear-assist-equips")).to_be_disabled()
    assert _config(page) == raw
    page.locator("#preset-assist-options summary").click()
    page.locator('[data-assist-option="assistMode"]').select_option("仅礼装")
    skill = page.locator('[data-assist-skill-index="0"]')
    skill.fill("11")
    skill.press("Tab")
    page.locator("#preset-run-options summary").click()
    page.locator('[data-run-option="stuckRestart"]').check()
    interval = page.locator('[data-run-option="checkStuckInterval"]')
    interval.fill("")
    interval.press_sequentially("1e")
    interval.press("Tab")
    page.locator("#add-assist-equip").click()
    playwright.expect(skill).to_have_value("11")
    assert interval.evaluate("e => e.validity.badInput")
    assert _config(page) == {**raw, "assistMode": "仅礼装", "stuckRestart": True, "assistEquip": ["First CE", "Second CE"]}
    page.locator("#cancel-preset").click()
    page.locator("#new-strategy").click()
    playwright.expect(page.locator("#preset-assist-equips")).to_be_hidden()
    page.close()


def test_catalog_failure_retry_and_stale_editor_response_do_not_change_script(tag_console):
    browser, url, directory = tag_console
    _equips(directory)
    page = browser.new_page()
    page.goto(url)
    playwright.expect(page.locator("#equip-template-list")).to_be_enabled()
    page.route("**/api/equip-templates", lambda route: route.fulfill(status=503, json={"error": {"message": "Catalog offline"}}))
    page.locator("#new-setting").click()
    page.locator("#preset-assist-equips summary").click()
    playwright.expect(page.locator("#preset-assist-equip-status")).to_contain_text("Catalog offline")
    playwright.expect(page.locator("#save-preset")).to_be_enabled()
    page.unroute("**/api/equip-templates")
    pending = []
    page.route("**/api/equip-templates", lambda route: pending.append(route))
    page.locator("#refresh-assist-equips").click()
    playwright.expect(page.locator("#preset-assist-equip-status")).to_contain_text("Loading")
    page.locator("#cancel-preset").click()
    page.locator("#new-setting").click()
    playwright.expect(page.locator("#preset-assist-equip-status")).to_contain_text("Loading")
    assert len(pending) == 2
    pending.pop(0).fulfill(json={"templates": [{"name": "Stale", "location": "active"}]})
    pending.pop(0).fulfill(json={"templates": [{"name": "Fresh", "location": "active"}]})
    playwright.expect(page.locator("#preset-assist-equip-source")).to_be_enabled()
    assert page.locator("#preset-assist-equip-source option").all_text_contents() == ["Fresh"]
    assert _config(page) == {"server": "CH", "round1_turns": 0}
    page.close()


def test_equip_controls_lock_during_pending_preset_and_save(tag_console):
    browser, url, directory = tag_console
    _equips(directory)
    page = browser.new_page()
    _entries, raw = _seed(page, url)
    raw["assistMode"] = "从者礼装"
    assert page.request.put(f"{url}/api/settings/demo", data={"config": raw, "overwrite": True}).ok
    page.goto(url)
    page.locator("#edit-setting").click()
    page.locator("#preset-assist-equips summary").click()
    pending = []
    page.route("**/api/strategies/Preset", lambda route: pending.append(route))
    response = page.request.get(f"{url}/api/strategies/Preset")
    page.locator("#apply-turn-strategy").click()
    playwright.expect(page.locator("#add-assist-equip")).to_be_disabled()
    pending.pop().fulfill(response=response)
    playwright.expect(page.locator("#add-assist-equip")).to_be_enabled()
    page.route("**/api/settings/demo", lambda route: pending.append(route))
    page.locator("#save-preset").click()
    playwright.expect(page.locator("#add-assist-equip")).to_be_disabled()
    pending.pop().fulfill(status=500, json={"error": {"message": "Save failed"}})
    playwright.expect(page.locator("#add-assist-equip")).to_be_enabled()
    page.close()


def test_catalog_refresh_keeps_latest_draft_and_mode_without_false_unavailable_labels(tag_console):
    browser, url, directory = tag_console
    _equips(directory)
    page = browser.new_page()
    page.goto(url)
    page.locator("#new-setting").click()
    page.locator("#preset-json").fill(json.dumps({"server": "CH", "assistEquip": ["First CE"]}))
    page.locator("#preset-assist-equips summary").click()
    playwright.expect(page.locator("#add-assist-equip")).to_be_enabled()
    pending = []
    page.route("**/api/equip-templates", lambda route: pending.append(route))
    page.locator("#refresh-assist-equips").click()
    playwright.expect(page.locator("#preset-assist-equip-status")).to_contain_text("Loading")
    playwright.expect(_row(page, "First CE").get_by_text("Unavailable", exact=True)).to_have_count(0)
    raw = {"server": "CH", "assistMode": "仅从者", "assistEquip": ["Second CE"], "custom": "latest"}
    page.locator("#preset-json").fill(json.dumps(raw))
    pending.pop().fulfill(json={"templates": [{"name": "First CE", "location": "active"}]})
    playwright.expect(_row(page, "Second CE")).to_contain_text("Unavailable")
    playwright.expect(page.locator("#add-assist-equip")).to_be_disabled()
    assert _config(page) == raw
    page.close()


def test_catalog_response_during_save_does_not_unlock_equip_controls(tag_console):
    browser, url, directory = tag_console
    _equips(directory)
    page = browser.new_page()
    page.goto(url)
    playwright.expect(page.locator("#equip-template-list")).to_be_enabled()
    catalogs, saves = [], []
    page.route("**/api/equip-templates", lambda route: catalogs.append(route))
    page.locator("#new-setting").click()
    page.locator("#preset-name").fill("Pending")
    raw = {"server": "CH", "round1_turns": 1, "assistEquip": ["First CE"]}
    page.locator("#preset-json").fill(json.dumps(raw))
    page.route("**/api/settings/Pending", lambda route: saves.append(route))
    page.locator("#save-preset").click()
    playwright.expect(page.locator("#clear-assist-equips")).to_be_disabled()
    catalogs.pop().fulfill(json={"templates": [{"name": "Second CE", "location": "active"}]})
    playwright.expect(page.locator("#preset-assist-equip-status")).to_have_text("1 CEs selected")
    playwright.expect(page.locator("#add-assist-equip")).to_be_disabled()
    assert _config(page) == raw
    saves.pop().fulfill(status=500, json={"error": {"message": "Save failed"}})
    playwright.expect(page.locator("#add-assist-equip")).to_be_enabled()
    page.close()


def test_large_equip_lists_cannot_be_extended_or_silently_rewritten(tag_console):
    browser, url, directory = tag_console
    _equips(directory)
    page = browser.new_page()
    page.goto(url)
    page.locator("#new-setting").click()
    raw = {"server": "CH", "assistEquip": [""] * 999, "custom": 1}
    page.locator("#preset-json").fill(json.dumps(raw))
    page.locator("#preset-assist-equips summary").click()
    playwright.expect(page.locator("#add-assist-equip")).to_be_enabled()
    page.locator("#add-assist-equip").click()
    playwright.expect(page.locator("#preset-error")).to_contain_text("1,000 values")
    assert _config(page) == raw
    raw["assistEquip"].append("First CE")
    page.locator("#preset-json").fill(json.dumps(raw))
    playwright.expect(page.locator("#preset-assist-equip-status")).to_contain_text("1,000 values")
    playwright.expect(page.locator("#add-assist-equip")).to_be_disabled()
    assert _config(page) == raw
    page.once("dialog", lambda dialog: dialog.accept())
    page.locator("#clear-assist-equips").click()
    assert _config(page) == {**raw, "assistEquip": []}
    page.close()


def test_failed_preview_and_long_names_keep_rows_usable_on_mobile(tag_console):
    browser, url, directory = tag_console
    _equips(directory)
    name = "Long-" + "W" * 80
    Image.new("RGB", (237, 68), "green").save(directory / "assets" / "assist" / "assist_equip" / f"{name}.png")
    page = browser.new_page(viewport={"width": 390, "height": 844})
    page.route("**/api/equip-templates/*/image?*", lambda route: route.fulfill(status=404))
    page.goto(url)
    page.locator("#new-setting").click()
    raw = {"server": "CH", "assistEquip": [name]}
    page.locator("#preset-json").fill(json.dumps(raw))
    page.locator("#preset-assist-equips summary").click()
    playwright.expect(_row(page, name)).to_contain_text("Preview unavailable")
    assert page.locator(".preset-form").evaluate("e => e.scrollWidth <= e.clientWidth")
    _row(page, name).get_by_role("button", name="Remove CE").click()
    assert _config(page) == {**raw, "assistEquip": []}
    playwright.expect(page.locator("#add-assist-equip")).to_be_focused()
    page.close()


def test_refresh_restores_keyboard_focus_without_stealing_new_focus(tag_console):
    browser, url, directory = tag_console
    _equips(directory)
    page = browser.new_page()
    page.goto(url)
    page.locator("#new-setting").click()
    page.locator("#preset-assist-equips summary").click()
    refresh = page.locator("#refresh-assist-equips")
    playwright.expect(refresh).to_be_enabled()
    pending = []
    page.route("**/api/equip-templates", lambda route: pending.append(route))
    refresh.focus()
    refresh.press("Enter")
    playwright.expect(refresh).to_be_disabled()
    pending.pop().fulfill(json={"templates": []})
    playwright.expect(refresh).to_be_focused()
    refresh.press("Enter")
    playwright.expect(refresh).to_be_disabled()
    page.locator("#preset-name").focus()
    pending.pop().fulfill(json={"templates": []})
    playwright.expect(refresh).to_be_enabled()
    playwright.expect(page.locator("#preset-name")).to_be_focused()
    assert _config(page) == {"server": "CH", "round1_turns": 0}
    page.close()


@pytest.mark.parametrize("phase", ["initial", "refresh"])
def test_removing_last_ce_during_catalog_load_focuses_section_summary(tag_console, phase):
    browser, url, directory = tag_console
    _equips(directory)
    page = browser.new_page()
    page.goto(url)
    playwright.expect(page.locator("#equip-template-list")).to_be_enabled()
    pending = []
    if phase == "initial":
        page.route("**/api/equip-templates", lambda route: pending.append(route))
    page.locator("#new-setting").click()
    raw = {"server": "CH", "assistEquip": ["First CE"]}
    page.locator("#preset-json").fill(json.dumps(raw))
    page.locator("#preset-assist-equips summary").click()
    if phase == "refresh":
        playwright.expect(page.locator("#refresh-assist-equips")).to_be_enabled()
        page.route("**/api/equip-templates", lambda route: pending.append(route))
        page.locator("#refresh-assist-equips").click()
    remove = _row(page, "First CE").get_by_role("button", name="Remove CE")
    remove.focus()
    remove.press("Enter")
    assert _config(page) == {**raw, "assistEquip": []}
    playwright.expect(page.locator("#preset-assist-equips summary")).to_be_focused()
    assert len(pending) == 1
    pending.pop().fulfill(json={"templates": []})
    playwright.expect(page.locator("#refresh-assist-equips")).to_be_enabled()
    playwright.expect(page.locator("#preset-assist-equips summary")).to_be_focused()
    page.close()


def test_adding_last_candidate_moves_focus_to_new_row(tag_console):
    browser, url, directory = tag_console
    _equips(directory)
    page = browser.new_page()
    page.goto(url)
    page.locator("#new-setting").click()
    page.locator("#preset-json").fill(json.dumps({"server": "CH", "assistEquip": ["First CE"]}))
    page.locator("#preset-assist-equips summary").click()
    add = page.locator("#add-assist-equip")
    playwright.expect(add).to_be_enabled()
    add.focus()
    add.press("Enter")
    playwright.expect(add).to_be_disabled()
    playwright.expect(_row(page, "Second CE").get_by_role("button", name="Remove CE")).to_be_focused()
    page.close()
