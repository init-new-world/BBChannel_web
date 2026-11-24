import json
import os
import re

import pytest
from PIL import Image, ImageDraw

playwright = pytest.importorskip("playwright.sync_api")
from tests.test_assist_tags_browser import tag_console
from tests.test_strategy_assignment_browser import _config, _seed

pytestmark = pytest.mark.skipif(
    not os.environ.get("BBCHANNEL_TEST_CHROMIUM"),
    reason="Set BBCHANNEL_TEST_CHROMIUM to a local Chromium executable.",
)


def _seed_visual_assets(directory):
    # Servant catalog + faces
    (directory / "data" / "servant_info_CH.json").write_text(
        json.dumps(
            {
                "Support": {"SN": "999", "class": "Caster", "star": 5},
                "光之高扬斯卡娅": {
                    "SN": "314",
                    "class": "Assassin",
                    "star": 5,
                    "NPcolor": "B",
                    "servant_face": 1,
                    "other_name": ["光狐", "杀狐"],
                    "skill_name": ["加攻"],
                    "skill_type": [1],
                },
                "阿尔托莉雅·卡斯特": {
                    "SN": "284",
                    "class": "Caster",
                    "star": 5,
                    "NPcolor": "A",
                    "servant_face": 1,
                    "other_name": ["术呆", "C呆"],
                    "skill_name": ["充能"],
                    "skill_type": [0],
                },
                "阿拉什": {
                    "SN": "016",
                    "class": "Archer",
                    "star": 1,
                    "NPcolor": "B",
                    "servant_face": 1,
                    "other_name": ["大英雄"],
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    faces_dir = directory / "assets" / "servantface"
    faces_dir.mkdir(parents=True, exist_ok=True)
    for s_name, color in [
        ("光之高扬斯卡娅", (210, 60, 90)),
        ("阿尔托莉雅·卡斯特", (50, 110, 210)),
        ("阿拉什", (180, 120, 50)),
    ]:
        Image.new("RGBA", (64, 64), color).save(faces_dir / f"{s_name}_1.png")

    # Master outfits + portraits + skill icons + skill details
    (directory / "data" / "master_info.json").write_text(
        json.dumps(
            {
                "魔术礼装·迦勒底": {
                    "SN": 1,
                    "skill_name": ["回复", "回避", "加攻"],
                    "skill_type": [1, 1, 1],
                },
                "决战用迦勒底制服": {
                    "SN": 7,
                    "skill_name": ["加攻", "眩晕", "换人"],
                    "skill_type": [0, 0, 3],
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (directory / "data" / "skill_details.json").write_text(
        json.dumps(
            {
                "masters": {
                    "1": [
                        {"name": "应急手当", "detail": "单体HP回复"},
                        {"name": "瞬间强化", "detail": "单体攻击提升"},
                        {"name": "紧急回避", "detail": "单体回避"},
                    ],
                    "7": [
                        {"name": "全体强化", "detail": "全体攻击与宝具威力提升"},
                        {"name": "甘狄拔", "detail": "敌方单体眩晕"},
                        {"name": "Order Change", "detail": "前排与后排换人"},
                    ],
                },
                "servants": {},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    masterface_dir = directory / "assets" / "masterface"
    masterface_dir.mkdir(parents=True, exist_ok=True)
    for m_name in ("魔术礼装·迦勒底", "决战用迦勒底制服"):
        Image.new("RGBA", (64, 64), (220, 50, 50, 255)).save(masterface_dir / f"{m_name}_0.png")
        Image.new("RGBA", (64, 64), (40, 90, 220, 255)).save(masterface_dir / f"{m_name}_1.png")

    skill_dir = directory / "assets" / "servant_skill"
    skill_dir.mkdir(parents=True, exist_ok=True)
    for sk_icon in ("回复", "回避", "加攻", "眩晕", "换人", "充能"):
        Image.new("RGBA", (36, 36), (35, 145, 95, 255)).save(skill_dir / f"{sk_icon}.png")

    # Assist CEs
    ce_dir = directory / "assets" / "assist" / "assist_equip"
    ce_dir.mkdir(parents=True, exist_ok=True)
    for ce_name, color in [("3plus", (80, 120, 190)), ("nff", (190, 95, 70)), ("宝石翁", (140, 80, 190))]:
        img = Image.new("RGB", (237, 68), color)
        ImageDraw.Draw(img).text((10, 24), ce_name, fill="white")
        img.save(ce_dir / f"{ce_name}.png")

    # Drop templates
    for sub_path, color in [("素材掉落检测模板图/金/蛮神心脏.png", (215, 165, 40)), ("礼装1582.jpg", (70, 150, 130))]:
        target = directory / "assets" / "drop" / sub_path
        target.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (88, 96), color).save(target)


def test_pro_mode_visual_pickers_and_ce_gallery(tag_console):
    browser, url, directory = tag_console
    _seed_visual_assets(directory)
    page = browser.new_page(viewport={"width": 1440, "height": 1000}, locale="zh-CN")
    page.set_default_timeout(10000)
    errors = []
    page.on("pageerror", lambda err: errors.append(str(err)))

    _entries, original = _seed(page, url)
    original.update({"assistMode": "从者礼装", "assistEquip": ["3plus"]})
    assert page.request.put(f"{url}/api/settings/demo", data={"config": original, "overwrite": True}).ok

    page.goto(url)
    page.locator("#edit-setting").click()

    # 1. Pro Mode Assist CEs: visual gallery + inline CE thumb
    page.locator("#preset-assist-equips summary").click()
    gallery_cards = page.locator("[data-equip-gallery-item]")
    playwright.expect(gallery_cards).to_have_count(3)
    page.wait_for_function(
        "document.querySelector('[data-equip-gallery-item=\"nff\"] img')?.naturalWidth === 237"
    )
    playwright.expect(page.locator('[data-equip-gallery-item="3plus"]')).to_have_class(re.compile(r"\bactive\b"))

    # Toggle 'nff' directly by clicking its visual gallery card
    page.locator('[data-equip-gallery-item="nff"]').click()
    assert _config(page)["assistEquip"] == ["3plus", "nff"]
    playwright.expect(page.locator('[data-equip-gallery-item="nff"]')).to_have_class(re.compile(r"\bactive\b"))

    # Filter gallery cards
    page.locator(".preset-equip-gallery-search").fill("宝石")
    playwright.expect(gallery_cards).to_have_count(1)
    page.locator('[data-equip-gallery-item="宝石翁"]').click()
    assert _config(page)["assistEquip"] == ["3plus", "nff", "宝石翁"]

    # 2. Pro Mode Team Servant Slot visual popover + inline avatar
    page.locator("#preset-team summary").click()
    slot0_wrapper = page.locator('[data-team-slot="0"]').locator("..")
    slot0_wrapper.dispatch_event("mousedown", {"button": 0})
    servant_popover = page.locator(".visual-popover-servant")
    playwright.expect(servant_popover).to_be_visible()
    page.wait_for_function(
        "document.querySelector('.visual-popover-servant .visual-select-option[data-visual-option-value=\"光之高扬斯卡娅\"] img')?.naturalWidth === 64"
    )
    # Search by nickname '术呆'
    servant_popover.locator(".visual-select-search").fill("术呆")
    caster_opt = servant_popover.locator('[data-visual-option-value="阿尔托莉雅·卡斯特"]')
    playwright.expect(caster_opt).to_be_visible()
    caster_opt.click()
    playwright.expect(servant_popover).not_to_be_visible()
    assert _config(page)["servant_0_name"] == "阿尔托莉雅·卡斯特"
    # Inline avatar beside slot 0 loads real image
    page.wait_for_function(
        "document.querySelector('[data-team-slot=\"0\"]').parentElement.querySelector('.visual-select-inline-thumb img')?.naturalWidth === 64"
    )

    # 3. Pro Mode Master Outfit visual popover with portraits, skills, and Escape handling
    page.locator("#preset-master-equip").dispatch_event("mousedown", {"button": 0})
    master_popover = page.locator(".visual-popover-master")
    playwright.expect(master_popover).to_be_visible()
    page.wait_for_function(
        "document.querySelector('.visual-popover-master [data-visual-option-value=\"7\"] .visual-thumb-box img')?.naturalWidth === 64"
    )
    # Escape closes only the popover, keeping preset-dialog open
    page.keyboard.press("Escape")
    playwright.expect(master_popover).not_to_be_visible()
    playwright.expect(page.locator("#preset-dialog")).to_be_visible()

    # Reopen, search '换人', select '决战用迦勒底制服' (SN 7)
    page.locator("#preset-master-equip").dispatch_event("mousedown", {"button": 0})
    master_popover.locator(".visual-select-search").fill("换人")
    playwright.expect(master_popover.locator('[data-visual-option-value="7"]')).to_be_visible()
    playwright.expect(master_popover.locator('[data-visual-option-value="1"]')).to_have_count(0)
    master_popover.locator('[data-visual-option-value="7"]').click()
    assert _config(page)["master_equip"] == 7

    # 4. Pro Mode Drop Stop visual popover
    page.locator("#preset-drop-options summary").click()
    playwright.expect(page.locator("#preset-drop-image option[value='drop/礼装1582.jpg']")).to_be_attached()
    page.locator("#preset-drop-image").dispatch_event("mousedown", {"button": 0})
    drop_popover = page.locator(".visual-popover-drop")
    playwright.expect(drop_popover).to_be_visible()
    page.wait_for_function(
        "document.querySelector('.visual-popover-drop [data-visual-option-value=\"drop/礼装1582.jpg\"] img')?.naturalWidth === 88"
    )
    drop_popover.locator('[data-visual-option-value="drop/素材掉落检测模板图/金/蛮神心脏.png"]').click()
    assert _config(page)["dropImage"] == "drop/素材掉落检测模板图/金/蛮神心脏.png"

    assert errors == []
    page.close()


def test_simple_wizard_master_outfit_visual_card_grid_and_review(tag_console):
    browser, url, directory = tag_console
    _seed_visual_assets(directory)
    page = browser.new_page(viewport={"width": 1280, "height": 900}, locale="zh-CN")
    page.set_default_timeout(10000)
    errors = []
    page.on("pageerror", lambda err: errors.append(str(err)))

    page.goto(url)
    page.locator("#new-setting-wizard").click()

    master_cards = page.locator("[data-wizard-master-sn]")
    playwright.expect(master_cards).to_have_count(3)  # None + 2 outfits
    page.wait_for_function(
        "document.querySelector('[data-wizard-master-sn=\"7\"] .wizard-master-card-avatar')?.naturalWidth === 64"
    )
    page.wait_for_function(
        "document.querySelector('[data-wizard-master-sn=\"7\"] .wizard-master-sk-icon')?.naturalWidth === 36"
    )

    # Filter to Order Change ('换人') outfits only
    page.locator(".wizard-master-box .wizard-filter-row .chip-button", has_text="换人").click()
    playwright.expect(master_cards).to_have_count(1)
    page.locator('[data-wizard-master-sn="7"]').click()
    assert _config(page)["master_equip"] == 7
    playwright.expect(page.locator(".wizard-master-summary-bar")).to_contain_text("决战用迦勒底制服")

    # Switching gender updates card portrait URL to sex=1
    page.locator(".wizard-top-row select").nth(1).select_option("1")
    playwright.expect(page.locator('[data-wizard-master-sn="7"] .wizard-master-card-avatar')).to_have_attribute(
        "src", re.compile(r"sex=1")
    )

    # Pick Assist CE in Step 2 and verify visual review pills in Step 4
    page.locator(".wizard-step-tab").nth(1).click()
    page.locator(".wizard-ce-card", has_text="nff").click()
    page.locator(".wizard-step-tab").nth(3).click()
    playwright.expect(page.locator(".wizard-review-master")).to_contain_text("决战用迦勒底制服")
    playwright.expect(page.locator(".wizard-review-ce")).to_contain_text("nff")

    assert errors == []
    page.close()


def test_visual_pickers_mobile_320px_no_horizontal_overflow(tag_console):
    browser, url, directory = tag_console
    _seed_visual_assets(directory)
    page = browser.new_page(viewport={"width": 320, "height": 720}, locale="en-US")
    page.set_default_timeout(10000)

    page.goto(url)
    page.locator("#new-setting-wizard").click()
    playwright.expect(page.locator("[data-wizard-master-sn]")).to_have_count(3)
    assert page.locator(".preset-form").evaluate("e => e.scrollWidth <= e.clientWidth")

    page.locator("#preset-mode-pro").click()
    for selector in ("#preset-team summary", "#preset-assist-equips summary", "#preset-drop-options summary"):
        page.locator(selector).click()
    assert page.locator(".preset-form").evaluate("e => e.scrollWidth <= e.clientWidth")

    # Popover clamps cleanly inside 320px viewport
    page.locator("#preset-master-equip").dispatch_event("mousedown", {"button": 0})
    popover = page.locator(".visual-popover-master")
    playwright.expect(popover).to_be_visible()
    box = popover.bounding_box()
    assert box["x"] >= 0 and box["x"] + box["width"] <= 320
    page.locator("#cancel-preset").click()

    # Tools tab Assist Equip Templates visual popover
    page.locator('[data-job-tab="tools"]').click()
    playwright.expect(page.locator("#equip-template-list")).to_be_enabled()
    page.locator("#equip-template-list").dispatch_event("mousedown", {"button": 0})
    equip_popover = page.locator('[data-visual-select-for="equip-template-list"]')
    playwright.expect(equip_popover).to_be_visible()
    page.wait_for_function(
        "document.querySelector('[data-visual-select-for=\"equip-template-list\"] [data-visual-option-value=\"active:nff\"] img')?.naturalWidth === 237"
    )
    equip_popover.locator('[data-visual-option-value="active:nff"]').click()
    playwright.expect(page.locator("#equip-template-list")).to_have_value("active:nff")
    page.close()


