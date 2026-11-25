from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest
from PIL import Image, ImageDraw

from webapp.core.errors import AppError, ErrorCode
from webapp.services.assist import AssistRecognizer
from webapp.services.battle_servants import FrontlineServantRecognizer
from webapp.services.equip_templates import MAIN_MATCH_BOX, TEMPLATE_SIZE, EquipTemplateService
from webapp.services.recognition import RecognitionService
from webapp.services.resources import ResourceService
from webapp.services.script_data import ScriptDataService
from webapp.services.wiki_sync import (
    WikiClient,
    WikiSyncService,
    crop_ce_banner,
    parse_ce_index,
    parse_ce_wikitext,
    parse_event_ce_ids,
    parse_gameinfo_sections,
    parse_servant_index,
    parse_servant_wikitext,
)


SAMPLE_SERVANT_INDEX = """
id=485
name_cn=杂贺孙一
name_jp=雑賀孫一
name_en=Saika Magoichi
name_link=杂贺孙一(Rider)
name_other=水孙一&泳装孙一
method=期间限定
tag=泳装&水着

id=465
name_cn=得墨忒耳
name_jp=デメテル
name_en=Demeter
name_link=得墨忒耳
name_other=农神
method=期间限定
tag=
"""

SAMPLE_SERVANT_WIKITEXT = """
==基础数值==
{{基础数值
|稀有度=4
|序号=485
|从者内部id=405900
|中文名=杂贺孙一
|日文名=雑賀孫一
|职阶=Rider
}}
==宝具==
<tabber>
强化后=
{{宝具
|中文名=八咫乌之夏
|卡色=Quick
}}
</tabber>
==技能==
===持有技能===
'''技能1（初期开放）'''
{{持有技能|绿放|狙击夏影 A|スナイプ・サマー A|8
|自身的Quick指令卡性能提升(3回合)<!--コメント-->
|20%|21%|22%|23%|24%|25%|26%|27%|28%|30%
|付与对{{特攻|天|〔拥有天之力的敌人〕|前缀=副属性}}特攻状态(3回合)
|20%|21%|22%|23%|24%|25%|26%|27%|28%|30%
}}
'''技能2（灵基再临第1阶段开放）'''
{{持有技能|无敌|八咫加护 B|ヤタの加護 B|8
|付与己方单体回避状态(2次·3回合)
|∅|||||||||
|暴击威力提升(3回合)
|20%|22%|24%|26%|28%|30%|32%|34%|36%|40%
}}
'''技能3（灵基再临第3阶段开放）'''
{{持有技能|充能|海滨战术 EX|ビーチ・タクティクス EX|8
|选择以下一项效果发动＆自身的NP增加
|20%|21%|22%|23%|24%|25%|26%|27%|28%|30%
}}
===职阶技能===
{{职阶技能|骑乘|騎乗|A|自身的Quick指令卡性能提升(10%)}}
"""

SAMPLE_CE_INDEX = """
id=2713
name=堂堂正正，川中岛决胜？！
name_link=いざ、尋常に川中島！？
name_other=川中岛
des=Arts&Buster 8% & NP 30%
des_max=Arts&Buster 10% & NP 50%[最大解放]
tag=
type=活动奖励
event=1

id=48
name=黑之圣杯
name_link=黑之圣杯
name_other=黑杯
des=宝具威力提升60%
des_max=宝具威力提升80%[最大解放]
tag=
type=卡池常驻
event=0
"""

SAMPLE_CE_WIKITEXT = """
{{概念礼装
|稀有度=5
|礼装id=2713
|礼装内部id=9409690
|名称=堂堂正正，川中岛决胜？！
|链接名=いざ、尋常に川中島！？
|图片名=川中岛礼装图
|日文名称=いざ、尋常に川中島！？
|持有技能=自身的Arts性能提升10%[最大解放]
|活动技能=活动期间攻击威力提升100%
|出场角色坐标=260,240;;410,310
}}
"""


def _make_patterned_png(size: tuple[int, int], *, seed: int = 11, rgba: bool = False) -> bytes:
    width, height = size
    img = Image.new("RGBA" if rgba else "RGB", size)
    pixels = []
    for y in range(height):
        for x in range(width):
            r = (x * 7 + y * 3 + seed * 17) % 256
            g = (x * 5 + y * 11 + seed * 29) % 256
            b = (x * 13 + y * 7 + seed * 43) % 256
            pixels.append((r, g, b, 255) if rgba else (r, g, b))
    img.putdata(pixels)
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_parsers_extract_nested_servant_ce_and_event_metadata() -> None:
    servants = parse_servant_index(SAMPLE_SERVANT_INDEX)
    assert [s.collection_no for s in servants] == [465, 485]
    saika_idx = servants[1]
    assert saika_idx.aliases == ("水孙一", "泳装孙一")

    parsed_svt = parse_servant_wikitext(SAMPLE_SERVANT_WIKITEXT, saika_idx)
    assert parsed_svt["sn"] == "405900"
    assert parsed_svt["class"] == "Rider"
    assert parsed_svt["star"] == 4
    assert parsed_svt["np_color"] == "Q"
    assert parsed_svt["skill_name"] == ["绿放", "无敌", "充能"]
    assert parsed_svt["skill_type"] == [0, 1, 0]
    assert parsed_svt["choice_skill_hints"] == [3]
    assert parsed_svt["skill_details"][0] == {
        "name": "狙击夏影 A",
        "detail": "自身的Quick指令卡性能提升(3回合)▲＆付与对〔拥有天之力的敌人〕特攻状态(3回合)▲",
    }
    assert parsed_svt["skill_details"][1] == {
        "name": "八咫加护 B",
        "detail": "付与己方单体回避状态(2次·3回合)＆暴击威力提升(3回合)▲",
    }

    ces = parse_ce_index(SAMPLE_CE_INDEX)
    assert [c.ce_id for c in ces] == [2713, 48]
    ce_detail = parse_ce_wikitext(SAMPLE_CE_WIKITEXT, ces[0])
    assert ce_detail["ce_id"] == 2713
    assert ce_detail["equip_sn"] == "9409690"
    assert ce_detail["focus_x"] == 260
    assert ce_detail["focus_y"] == 240
    assert ce_detail["image_name"] == "川中岛礼装图"

    gameinfo = parse_gameinfo_sections(
        '*从者总数：<section class="lst" begin=cnsvts />458<section class="lst" end=cnsvts />'
        '*礼装：<section class="lst" begin=jpces />2720<section class="lst" end=jpces />'
    )
    assert gameinfo == {"cnsvts": "458", "jpces": "2720"}

    event_ids, related = parse_event_ce_ids(
        "{{活动信息|主关联页=盈月剑风帖}}\n{{活动加成礼装|礼装序号=\n1969\n1966,1967,1968\n}}"
    )
    assert event_ids == [1969, 1966, 1967, 1968]
    assert related == ["盈月剑风帖"]


def test_crop_ce_banner_respects_focus_y_and_clamps_offsets() -> None:
    card = _make_patterned_png((512, 875), seed=5)
    png_default, meta_default = crop_ce_banner(card, focus_y=240, y_offset=0)
    with Image.open(BytesIO(png_default)) as cropped:
        assert cropped.size == TEMPLATE_SIZE
        assert cropped.mode == "RGB"
    assert meta_default["crop_box"] == [6, 168, 506, 312]
    assert meta_default["effective_center_y"] == 240

    _, meta_top = crop_ce_banner(card, focus_y=50, y_offset=-200)
    assert meta_top["crop_box"] == [6, 0, 506, 144]

    _, meta_bottom = crop_ce_banner(card, focus_y=850, y_offset=200)
    assert meta_bottom["crop_box"] == [6, 875 - 144, 506, 875]


def test_wiki_client_rejects_html_challenge_responses() -> None:
    def fake_http(url: str, _headers: dict[str, str], _timeout: float) -> tuple[int, dict[str, str], bytes]:
        return 200, {"Content-Type": "text/html; charset=utf-8"}, b"<html>Please verify</html>"

    client = WikiClient(cache_dir=None, http_get=fake_http)
    with pytest.raises(AppError) as exc_info:
        client.mw_api({"action": "query"})
    assert exc_info.value.code == ErrorCode.WIKI_UPSTREAM_FAILED


def test_sync_servants_writes_catalog_skills_faces_commands_and_status_sheet(tmp_path: Path) -> None:
    assets = tmp_path / "assets"
    data = tmp_path / "data"
    (assets / "status").mkdir(parents=True)
    data.mkdir(parents=True)

    existing_servant = {
        "得墨忒耳": {
            "skill_name": ["蓝绿放", "毅力", "加攻"],
            "skill_type": [0, 1, 0],
            "star": 5,
            "class": "Lancer",
            "SN": "306400",
            "command_card_types": 3,
            "graph_types": 4,
            "servant_face_types": 4,
            "other_name": ["农神"],
            "graph": 1,
            "command_card": 1,
            "servant_face": 1,
            "NPcolor": "A",
        }
    }
    for srv in ("CH", "CNTW", "JP"):
        (data / f"servant_info_{srv}.json").write_text(
            json.dumps(existing_servant, ensure_ascii=False),
            encoding="utf-8",
        )
    (data / "skill_details.json").write_text(
        json.dumps({"servants": {}, "masters": {}}, ensure_ascii=False),
        encoding="utf-8",
    )
    Image.new("RGB", (500, 55), (10, 10, 10)).save(assets / "status" / "Rider.png")
    (assets / "status" / "status_info.json").write_text(
        json.dumps({"Rider": ["旧骑兵_1.png"]}, ensure_ascii=False),
        encoding="utf-8",
    )

    skill_png = _make_patterned_png((110, 110), seed=1, rgba=True)
    face_png = _make_patterned_png((128, 128), seed=2, rgba=True)
    cmd_png = _make_patterned_png((256, 256), seed=3, rgba=True)
    status_png = _make_patterned_png((256, 256), seed=4, rgba=True)

    def fake_http(url: str, _headers: dict[str, str], _timeout: float) -> tuple[int, dict[str, str], bytes]:
        if "fgo.wiki/api.php" in url:
            if "imageinfo" in url:
                payload: dict[str, Any] = {
                    "query": {
                        "pages": {
                            "1": {"title": "文件:绿放.png", "imageinfo": [{"url": "https://cdn.test/skill_q.png"}]},
                            "2": {"title": "文件:无敌.png", "imageinfo": [{"url": "https://cdn.test/skill_inv.png"}]},
                            "3": {"title": "文件:充能.png", "imageinfo": [{"url": "https://cdn.test/skill_np.png"}]},
                        }
                    }
                }
            elif "%E8%8B%B1%E7%81%B5%E5%9B%BE%E9%89%B4" in url:
                payload = {
                    "query": {
                        "pages": {
                            "10": {
                                "title": "英灵图鉴/数据",
                                "revisions": [{"slots": {"main": {"*": SAMPLE_SERVANT_INDEX}}}],
                            }
                        }
                    }
                }
            elif "Gameinfo" in url:
                payload = {
                    "query": {
                        "pages": {
                            "11": {
                                "title": "Mooncell:Gameinfo/国服/灵基一览",
                                "revisions": [{"slots": {"main": {"*": '<section class="lst" begin=cnsvts />465<section class="lst" end=cnsvts />'}}}],
                            }
                        }
                    }
                }
            else:
                payload = {
                    "query": {
                        "pages": {
                            "20": {
                                "title": "杂贺孙一(Rider)",
                                "revisions": [{"slots": {"main": {"*": SAMPLE_SERVANT_WIKITEXT}}}],
                            },
                            "21": {
                                "title": "得墨忒耳",
                                "revisions": [
                                    {
                                        "slots": {
                                            "main": {
                                                "*": "{{基础数值|稀有度=5|序号=465|从者内部id=306400|中文名=得墨忒耳|职阶=Lancer}}"
                                            }
                                        }
                                    }
                                ],
                            },
                        }
                    }
                }
            return 200, {"Content-Type": "application/json"}, json.dumps(payload).encode("utf-8")

        if "api.atlasacademy.io/nice/JP/servant/405900" in url:
            atlas_payload = {
                "id": 405900,
                "extraAssets": {
                    "faces": {
                        "ascension": {"1": "https://cdn.test/face1.png", "2": "https://cdn.test/face2.png"},
                        "costume": {},
                    },
                    "commands": {
                        "ascension": {"1": "https://cdn.test/cmd1.png", "2": "https://cdn.test/cmd2.png", "3": "https://cdn.test/cmd3.png"},
                        "costume": {"405930": "https://cdn.test/cmd_costume.png"},
                    },
                    "status": {
                        "ascension": {"1": "https://cdn.test/st1.png", "2": "https://cdn.test/st2.png"},
                        "costume": {},
                    },
                    "charaGraph": {"ascension": {"1": "https://cdn.test/cg1.png"}},
                },
            }
            return 200, {"Content-Type": "application/json"}, json.dumps(atlas_payload).encode("utf-8")

        if "skill_" in url:
            return 200, {"Content-Type": "image/png"}, skill_png
        if "face" in url:
            return 200, {"Content-Type": "image/png"}, face_png
        if "cmd" in url:
            return 200, {"Content-Type": "image/png"}, cmd_png
        if "st" in url:
            return 200, {"Content-Type": "image/png"}, status_png
        raise AssertionError(f"Unexpected URL: {url}")

    resources = ResourceService(assets, data)
    equip_templates = EquipTemplateService(resources)
    script_data = ScriptDataService(data, resources=resources)
    battle_servants = FrontlineServantRecognizer(resources)
    # Prime caches before sync to verify invalidation
    _ = script_data.list_servants("CH")
    _ = battle_servants.resolve_servant_metadata("CH", "得墨忒耳")

    svc = WikiSyncService(
        resources,
        equip_templates,
        script_data=script_data,
        battle_servants=battle_servants,
        client=WikiClient(cache_dir=tmp_path / ".cache", http_get=fake_http),
    )

    dry = svc.sync_servants(dry_run=True)
    assert dry["synced_count"] == 1
    assert "杂贺孙一(Rider)" not in json.loads((data / "servant_info_CH.json").read_text(encoding="utf-8"))

    synced = svc.sync_servants(dry_run=False)
    assert synced["synced_count"] == 1
    assert len(synced["warnings"]) == 1  # choice skill hint on skill 3

    servants_api = script_data.list_servants("CH")["servants"]
    added = next(item for item in servants_api if item["name"] == "杂贺孙一(Rider)")
    assert added["sn"] == "405900"
    assert added["skill_details"][0]["name"] == "狙击夏影 A"
    assert battle_servants.resolve_servant_metadata("CH", "水孙一")["canonical_name"] == "杂贺孙一(Rider)"

    with Image.open(assets / "servantface" / "杂贺孙一(Rider)_1.png") as face_im:
        assert face_im.size == (130, 130)
    with Image.open(assets / "servant_skill" / "绿放.png") as sk_im:
        assert sk_im.size == (110, 110)
    assert (assets / "commands_JP" / "405900" / "card_servant_1.png").is_file()
    assert (assets / "commands_JP" / "405900" / "405930.png").is_file()

    status_info = json.loads((assets / "status" / "status_info.json").read_text(encoding="utf-8"))
    assert status_info["Rider"] == ["旧骑兵_1.png", "杂贺孙一(Rider)_1.png", "杂贺孙一(Rider)_2.png"]


def test_assist_recognizer_with_equip_main_mask_ignores_event_drop_and_mlb_corners(tmp_path: Path) -> None:
    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")

    assets = tmp_path / "assets"
    data = tmp_path / "data"
    (assets / "assist" / "assist_equip").mkdir(parents=True)
    data.mkdir(parents=True)

    # Create explicit 237x68 mask matching assets/assist/equip_main_mask.png
    mask = Image.new("L", TEMPLATE_SIZE, 0)
    left, top, right, bottom = MAIN_MATCH_BOX
    ImageDraw.Draw(mask).rectangle((left, top, right - 1, bottom - 1), fill=255)
    mask.save(assets / "assist" / "equip_main_mask.png")

    card_art = _make_patterned_png((512, 875), seed=73)
    cropped_png, _ = crop_ce_banner(card_art, focus_y=240, y_offset=0)
    (assets / "assist" / "assist_equip" / "川中岛.png").write_bytes(cropped_png)

    # Simulate in-game 1280x720 support list where the 237x68 CE banner has BOTH:
    # - a bright "+2" event drop bonus icon painted over bottom-left (0..38, 40..68)
    # - a bright yellow MLB diamond star painted over bottom-right (195..235, 34..68)
    in_game_banner = Image.open(BytesIO(cropped_png)).convert("RGB")
    draw = ImageDraw.Draw(in_game_banner)
    draw.rectangle((0, 38, 38, 67), fill=(255, 255, 255))
    draw.rectangle((40, 57, 120, 67), fill=(250, 240, 40))
    draw.polygon([(212, 35), (230, 51), (212, 67), (195, 51)], fill=(255, 235, 60))

    scale = 2 / 3
    scaled_banner = Image.fromarray(
        cv2.resize(
            np.asarray(in_game_banner),
            (round(237 * scale), round(68 * scale)),
            interpolation=cv2.INTER_AREA,
        )
    )
    screen = Image.new("RGB", (1280, 720), (24, 30, 42))
    screen.paste(scaled_banner, (120, 260))
    buf = BytesIO()
    screen.save(buf, format="PNG")

    resources = ResourceService(assets, data)
    recognizer = AssistRecognizer(resources, RecognitionService(resources))
    result = recognizer.recognize(
        buf.getvalue(),
        {"mode": "仅礼装", "equip_names": ["川中岛"]},
        threshold=0.95,
    )

    assert result["candidate_count"] == 1
    cand = result["candidates"][0]
    assert cand["checks"]["equip_name"] == "川中岛"
    assert cand["confidence"] >= 0.98
    assert cand["bounds"] == [120, 260, round(237 * scale), round(68 * scale)]


def test_assist_recognizer_handles_nonstandard_ce_size_and_lfs_pointer_mask(tmp_path: Path):
    pytest.importorskip("cv2")
    assets = tmp_path / "assets"
    data = tmp_path / "data"
    (assets / "assist" / "assist_equip").mkdir(parents=True)
    data.mkdir(parents=True)

    # 1. Valid 237x68 mask + legacy 236x68 CE template (like real 未满破_Dec23_0.png) must NOT crash
    mask = Image.new("L", TEMPLATE_SIZE, 0)
    left, top, right, bottom = MAIN_MATCH_BOX
    ImageDraw.Draw(mask).rectangle((left, top, right - 1, bottom - 1), fill=255)
    mask.save(assets / "assist" / "equip_main_mask.png")

    legacy_ce = _make_patterned_png((236, 68), seed=19)
    (assets / "assist" / "assist_equip" / "legacy236.png").write_bytes(legacy_ce)

    screen = Image.new("RGB", (1280, 720), (24, 30, 42))
    buf = BytesIO()
    screen.save(buf, format="PNG")

    resources = ResourceService(assets, data)
    recognizer = AssistRecognizer(resources, RecognitionService(resources))
    res1 = recognizer.recognize(buf.getvalue(), {"mode": "仅礼装", "equip_names": ["legacy236"]}, threshold=0.95)
    assert res1["candidate_count"] == 0

    # 2. Un-pulled Git LFS text pointer as equip_main_mask.png must safely fall back without crashing
    (assets / "assist" / "equip_main_mask.png").write_text(
        "version https://git-lfs.github.com/spec/v1\noid sha256:0000\nsize 160\n",
        encoding="utf-8",
    )
    recognizer2 = AssistRecognizer(resources, RecognitionService(resources))
    res2 = recognizer2.recognize(buf.getvalue(), {"mode": "仅礼装", "equip_names": ["legacy236"]}, threshold=0.95)
    assert res2["candidate_count"] == 0


def test_wiki_client_rejects_disallowed_schemes_and_hosts():
    from webapp.services.wiki_sync import _validate_upstream_url

    assert _validate_upstream_url("https://fgo.wiki/api.php")
    assert _validate_upstream_url("https://static.atlasacademy.io/JP/Faces/f_1001000.png")

    with pytest.raises(AppError):
        _validate_upstream_url("file:///etc/passwd")
    with pytest.raises(AppError):
        _validate_upstream_url("http://fgo.wiki/api.php")
    with pytest.raises(AppError):
        _validate_upstream_url("https://169.254.169.254/latest/meta-data/")


def test_import_ce_preserves_archive_and_checks_drop_conflict_before_writing(tmp_path: Path):
    assets = tmp_path / "assets"
    data = tmp_path / "data"
    (assets / "equipmaker" / "assist_equip_store").mkdir(parents=True)
    (assets / "equipmaker" / "equip_check_store").mkdir(parents=True)
    (assets / "drop").mkdir(parents=True)
    data.mkdir(parents=True)

    # Existing archive template + precise _0/_1 crops must remain untouched when activating new CE
    orig_archive = _make_patterned_png(TEMPLATE_SIZE, seed=3)
    (assets / "equipmaker" / "assist_equip_store" / "活动礼装A.png").write_bytes(orig_archive)
    (assets / "equipmaker" / "equip_check_store" / "活动礼装A_0.png").write_bytes(_make_patterned_png((34, 34), seed=4))

    ce_index_text = "id=2500\nname=活动礼装A\nname_link=活动礼装A\n"
    ce_page_text = "{{概念礼装|礼装id=2500|名称=活动礼装A|图片名=礼装2500|出场角色坐标=256,220}}"
    card_art = _make_patterned_png((512, 875), seed=55)

    def fake_http(url: str, _headers: dict[str, str], _timeout: float):
        if "fgo.wiki/api.php" in url and "imageinfo" in url:
            return 200, {"content-type": "application/json"}, json.dumps({
                "query": {"pages": {"1": {"title": "File:礼装2500.png", "imageinfo": [{"url": "https://fgo.wiki/images/ce2500.png"}]}}}
            }).encode()
        if "fgo.wiki/api.php" in url:
            if "%E7%A4%BC%E8%A3%85%E5%9B%BE%E9%89%B4" in url:
                pages = {"1": {"title": "礼装图鉴/数据", "revisions": [{"slots": {"main": {"*": ce_index_text}}}]}}
            else:
                pages = {"2": {"title": "活动礼装A", "revisions": [{"slots": {"main": {"*": ce_page_text}}}]}}
            return 200, {"content-type": "application/json"}, json.dumps({"query": {"pages": pages}}).encode()
        if url == "https://fgo.wiki/images/ce2500.png":
            return 200, {"content-type": "image/png"}, card_art
        return 404, {}, b""

    resources = ResourceService(assets, data)
    equip_templates = EquipTemplateService(resources, RecognitionService(resources))
    svc = WikiSyncService(resources, equip_templates, client=WikiClient(http_get=fake_http, cache_dir=None))

    # Pre-create conflicting drop file -> must fail BEFORE writing active assist_equip template!
    (assets / "drop" / "活动礼装A.png").write_bytes(b"existing-drop")
    with pytest.raises(AppError) as exc_info:
        svc.import_craft_essence(2500, activate=True, save_drop=True, overwrite=False)
    assert exc_info.value.code == ErrorCode.DATA_FILE_CONFLICT
    assert not (assets / "assist" / "assist_equip" / "活动礼装A.png").exists()

    # Now import with save_drop=False, activate=True -> archive & its _0 crop remain completely intact!
    result = svc.import_craft_essence(2500, activate=True, save_drop=False, overwrite=False)
    assert result["template"]["location"] == "active"
    assert (assets / "assist" / "assist_equip" / "活动礼装A.png").is_file()
    assert (assets / "equipmaker" / "assist_equip_store" / "活动礼装A.png").read_bytes() == orig_archive
    assert (assets / "equipmaker" / "equip_check_store" / "活动礼装A_0.png").is_file()

