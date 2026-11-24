from __future__ import annotations

import json
import time
from io import BytesIO
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from PIL import Image

from webapp.app import create_app
from webapp.services.equip_templates import EquipTemplateService
from webapp.services.resources import ResourceService
from webapp.services.script_data import ScriptDataService
from webapp.services.wiki_sync import WikiClient, WikiSyncService
from webapp.tools.wiki_sync import main as cli_main


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

SAMPLE_EVENT_PAGE = """
{{活动信息|类型=Event}}
==活动礼装==
{{活动加成礼装
|礼装序号=
2713
}}
"""

SAMPLE_CE_2713_PAGE = """
{{概念礼装
|稀有度=5
|礼装id=2713
|礼装内部id=9409690
|名称=堂堂正正，川中岛决胜？！
|链接名=いざ、尋常に川中島！？
|图片名=いざ、尋常に川中島！？
|日文名称=いざ、尋常に川中島！？
|出场角色坐标=256,220
}}
"""


def _png_bytes(size: tuple[int, int], color: tuple[int, int, int]) -> bytes:
    img = Image.new("RGB", size, color)
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _build_fake_wiki_service(tmp_path: Path, *, fail_upstream: bool = False) -> tuple[Path, Path, WikiSyncService]:
    assets = tmp_path / "assets"
    data = tmp_path / "data"
    assets.mkdir(parents=True, exist_ok=True)
    data.mkdir(parents=True, exist_ok=True)
    for srv in ("CH", "CNTW", "JP"):
        (data / f"servant_info_{srv}.json").write_text("{}", encoding="utf-8")

    now = int(time.time())
    card_art = _png_bytes((512, 875), (80, 120, 200))
    drop_icon = _png_bytes((132, 144), (200, 140, 60))

    def fake_http(url: str, _headers: dict[str, str], _timeout: float) -> tuple[int, dict[str, str], bytes]:
        if fail_upstream:
            return 503, {"Content-Type": "text/html"}, b"Service Unavailable"

        if "action=ask" in url:
            payload: dict[str, Any] = {
                "query": {
                    "results": {
                        "唠唠叨叨软软弹弹战争": {
                            "printouts": {
                                "EventNameJP": ["唠唠叨叨软软弹弹战争"],
                                "EventStart": [{"timestamp": str(now - 3600)}],
                                "EventEnd": [{"timestamp": str(now + 86400)}],
                                "EventStartJP": [{"timestamp": str(now - 3600)}],
                                "EventEndJP": [{"timestamp": str(now + 86400)}],
                                "EventType": ["Event"],
                            }
                        }
                    }
                }
            }
            return 200, {"Content-Type": "application/json"}, json.dumps(payload).encode("utf-8")

        if "imageinfo" in url:
            payload = {
                "query": {
                    "pages": {
                        "1": {
                            "title": "文件:いざ、尋常に川中島！？.png",
                            "imageinfo": [{"url": "https://cdn.test/ce2713_art.png"}],
                        },
                        "2": {
                            "title": "文件:礼装2713.jpg",
                            "imageinfo": [{"url": "https://cdn.test/ce2713_drop.jpg"}],
                        },
                    }
                }
            }
            return 200, {"Content-Type": "application/json"}, json.dumps(payload).encode("utf-8")

        if "fgo.wiki/api.php" in url:
            pages: dict[str, Any] = {
                "1": {
                    "title": "礼装图鉴/数据",
                    "revisions": [{"slots": {"main": {"*": SAMPLE_CE_INDEX}}}],
                },
                "2": {
                    "title": "唠唠叨叨软软弹弹战争",
                    "revisions": [{"slots": {"main": {"*": SAMPLE_EVENT_PAGE}}}],
                },
                "3": {
                    "title": "いざ、尋常に川中島！？",
                    "revisions": [{"slots": {"main": {"*": SAMPLE_CE_2713_PAGE}}}],
                },
                "4": {
                    "title": "Mooncell:Gameinfo/国服/灵基一览",
                    "revisions": [
                        {
                            "slots": {
                                "main": {
                                    "*": (
                                        '<section class="lst" begin=cnsvts />458<section class="lst" end=cnsvts />'
                                        '<section class="lst" begin=cnprevces />2709<section class="lst" end=cnprevces />'
                                        '<section class="lst" begin=cnces />2713<section class="lst" end=cnces />'
                                    )
                                }
                            }
                        }
                    ],
                },
                "5": {
                    "title": "Mooncell:Gameinfo/日服/灵基一览",
                    "revisions": [
                        {
                            "slots": {
                                "main": {
                                    "*": (
                                        '<section class="lst" begin=jpsvts />487<section class="lst" end=jpsvts />'
                                        '<section class="lst" begin=jpprevces />2709<section class="lst" end=jpprevces />'
                                        '<section class="lst" begin=jpces />2713<section class="lst" end=jpces />'
                                    )
                                }
                            }
                        }
                    ],
                },
                "6": {
                    "title": "英灵图鉴/数据",
                    "revisions": [{"slots": {"main": {"*": ""}}}],
                },
            }
            return 200, {"Content-Type": "application/json"}, json.dumps({"query": {"pages": pages}}).encode("utf-8")

        if url == "https://cdn.test/ce2713_art.png":
            return 200, {"Content-Type": "image/png"}, card_art
        if url == "https://cdn.test/ce2713_drop.jpg":
            return 200, {"Content-Type": "image/jpeg"}, drop_icon
        raise AssertionError(f"Unexpected URL: {url}")

    resources = ResourceService(assets, data)
    equip_templates = EquipTemplateService(resources)
    script_data = ScriptDataService(data, resources=resources)
    wiki_sync = WikiSyncService(
        resources,
        equip_templates,
        script_data=script_data,
        client=WikiClient(cache_dir=None, http_get=fake_http),
    )
    return assets, data, wiki_sync


def test_wiki_equip_endpoints_list_preview_import_and_conflict(tmp_path: Path) -> None:
    assets, data, wiki_sync = _build_fake_wiki_service(tmp_path)
    app = create_app(
        assets_dir=assets,
        data_dir=data,
        runtime_db_path=tmp_path / "runtime.db",
        wiki_sync=wiki_sync,
    )
    with TestClient(app) as client:
        events_resp = client.get("/api/wiki/events?server=JP")
        assert events_resp.status_code == 200
        ev_payload = events_resp.json()
        assert ev_payload["events"][0]["title"] == "唠唠叨叨软软弹弹战争"
        assert ev_payload["events"][0]["active"] is True
        assert ev_payload["events"][0]["craft_essences"][0]["ce_id"] == 2713

        search_resp = client.get("/api/wiki/craft-essences?query=黑杯")
        assert search_resp.status_code == 200
        assert search_resp.json()["items"][0]["ce_id"] == 48

        preview_resp = client.get("/api/wiki/craft-essences/2713/preview?y_offset=18")
        assert preview_resp.status_code == 200
        preview = preview_resp.json()
        assert preview["crop"]["effective_center_y"] == 238
        assert preview["preview_base64"]

        import_resp = client.post(
            "/api/wiki/craft-essences/2713/import",
            json={
                "name": "川中岛礼装",
                "y_offset": 18,
                "activate": True,
                "save_drop": True,
                "overwrite": False,
            },
        )
        assert import_resp.status_code == 200
        imported = import_resp.json()
        assert imported["template"]["location"] == "active"
        assert imported["drop_template_path"] == "drop/川中岛礼装.png"
        assert (assets / "assist" / "assist_equip" / "川中岛礼装.png").is_file()
        assert (assets / "drop" / "川中岛礼装.png").is_file()

        # Duplicate without overwrite returns 409 conflict
        conflict_resp = client.post(
            "/api/wiki/craft-essences/2713/import",
            json={"name": "川中岛礼装", "activate": True, "overwrite": False},
        )
        assert conflict_resp.status_code == 409
        assert conflict_resp.json()["error"]["code"] == "data_file_conflict"

        # Retry with overwrite=True succeeds
        replace_resp = client.post(
            "/api/wiki/craft-essences/2713/import",
            json={"name": "川中岛礼装", "activate": True, "overwrite": True},
        )
        assert replace_resp.status_code == 200


def test_wiki_upstream_failure_returns_502(tmp_path: Path) -> None:
    assets, data, wiki_sync = _build_fake_wiki_service(tmp_path, fail_upstream=True)
    app = create_app(
        assets_dir=assets,
        data_dir=data,
        runtime_db_path=tmp_path / "runtime.db",
        wiki_sync=wiki_sync,
    )
    with TestClient(app) as client:
        resp = client.get("/api/wiki/events?server=CH")
        assert resp.status_code == 502
        assert resp.json()["error"]["code"] == "wiki_upstream_failed"


def test_wiki_sync_cli_commands_execute_cleanly(tmp_path: Path, capsys) -> None:
    assets, _data, wiki_sync = _build_fake_wiki_service(tmp_path)

    rc_check = cli_main(["check", "--server", "JP", "--json"], service=wiki_sync)
    assert rc_check == 0
    check_out = json.loads(capsys.readouterr().out)
    assert "JP" in check_out["events"]

    rc_ce = cli_main(
        ["sync-event-ces", "--server", "JP", "--activate", "--save-drop", "--json"],
        service=wiki_sync,
    )
    assert rc_ce == 0
    ce_out = json.loads(capsys.readouterr().out)
    assert ce_out["count"] == 1
    assert (assets / "assist" / "assist_equip" / "堂堂正正，川中岛决胜？！.png").is_file()
