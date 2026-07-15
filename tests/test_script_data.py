import json
from pathlib import Path

import pytest

from webapp.core.errors import AppError, ErrorCode
from webapp.services.script_data import ScriptDataService


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _strategy_payload() -> dict:
    return {
        "card1": {"type": 0, "cards": [1], "criticalStar": 0, "more_or_less": True},
        "card2": {"type": 1, "cards": ["1B"], "criticalStar": 0, "more_or_less": True},
        "card3": {"type": 2, "cards": [], "criticalStar": 0, "more_or_less": True},
        "breakpoint": [False, False],
        "colorFirst": True,
    }


def test_lists_settings_and_strategies_by_stem(tmp_path: Path):
    _write_json(tmp_path / "settings" / "beta.json", {})
    _write_json(tmp_path / "settings" / "alpha.json", {})
    _write_json(tmp_path / "settings" / "notes.txt", {})
    _write_json(tmp_path / "strategy" / "brave.json", [])

    service = ScriptDataService(tmp_path)

    assert service.list_settings() == [
        {"name": "alpha", "path": "settings/alpha.json"},
        {"name": "beta", "path": "settings/beta.json"},
    ]
    assert service.list_strategies() == [
        {"name": "brave", "path": "strategy/brave.json"},
    ]


def test_get_setting_returns_config_summary_and_validation(tmp_path: Path):
    _write_json(
        tmp_path / "servant_info_CH.json",
        {
            "Servant A": {"other_name": ["A"], "class": "Caster", "SN": "100"},
            "Altria Caster": {"other_name": ["Caber"], "class": "Caster", "SN": "101"},
        },
    )
    _write_json(
        tmp_path / "settings" / "demo.json",
        {
            "server": "CH",
            "servant_0_name": "Servant A",
            "servant_1_name": "Caber",
            "servant_2_name": None,
            "round1_turns": 1,
            "round1_turn0_skill": [1, [2, 1]],
            "round1_turn0_np": [1],
            "round1_turn0_strategy": [_strategy_payload()],
        },
    )

    detail = ScriptDataService(tmp_path).get_setting("demo")

    assert detail["name"] == "demo"
    assert detail["path"] == "settings/demo.json"
    assert detail["config"]["server"] == "CH"
    assert detail["summary"]["server"] == "CH"
    assert detail["summary"]["servants"] == ["Servant A", "Caber"]
    assert detail["summary"]["turn_count"] == 1
    assert detail["summary"]["strategy_count"] == 1
    assert detail["validation"] == {"ok": True, "errors": [], "warnings": []}


def test_get_setting_plan_normalizes_round_turn_actions(tmp_path: Path):
    _write_json(
        tmp_path / "servant_info_CH.json",
        {
            "Servant A": {"other_name": [], "class": "Caster", "SN": "100"},
            "Support B": {"other_name": ["B"], "class": "Rider", "SN": "101"},
        },
    )
    strategy = _strategy_payload()
    _write_json(
        tmp_path / "settings" / "demo.json",
        {
            "server": "CH",
            "servant_0_name": "Servant A",
            "servant_1_name": "B",
            "servant_2_name": None,
            "usedServant": [0, 1],
            "master_equip": 7,
            "master_sex": 1,
            "round1_extraSkill": [["extra", 1]],
            "round1_extraStrategy": [strategy],
            "round1_turns": 2,
            "round1_turn0_replace": {"2": 4, "4": None},
            "round1_turn0_skill": [1, [2, 1]],
            "round1_turn0_np": [1],
            "round1_turn0_strategy": [strategy],
            "round1_turn0_condition": {"card": "1B"},
            "round1_turn1_skill": [],
            "round1_turn1_np": [],
            "round2_turns": 0,
        },
    )

    plan = ScriptDataService(tmp_path).get_setting_plan("demo")

    assert plan["name"] == "demo"
    assert plan["server"] == "CH"
    assert plan["validation"]["ok"] is True
    assert plan["servants"] == [
        {"slot": 0, "name": "Servant A", "active": True},
        {"slot": 1, "name": "B", "active": True},
        {"slot": 2, "name": None, "active": False},
        {"slot": 3, "name": None, "active": False},
        {"slot": 4, "name": None, "active": False},
        {"slot": 5, "name": None, "active": False},
    ]
    assert plan["master"] == {"equip": 7, "sex": 1}
    assert plan["rounds"][0]["round"] == 1
    assert plan["rounds"][0]["extra_skill"] == [["extra", 1]]
    assert plan["rounds"][0]["extra_strategy"] == [strategy]
    assert plan["rounds"][0]["turns"][0] == {
        "round": 1,
        "turn": 0,
        "skills": [1, [2, 1]],
        "nps": [1],
        "strategy": [strategy],
        "condition": {"card": "1B"},
        "replace": {"2": 4, "4": None},
        "actions": [
            {"type": "replace", "replacements": {"2": 4, "4": None}},
            {"type": "skill", "command": 1},
            {"type": "skill", "command": [2, 1]},
            {"type": "np", "servant": 1},
            {"type": "strategy", "strategies": [strategy]},
        ],
    }
    assert plan["summary"]["round_count"] == 1
    assert plan["summary"]["action_count"] == 5


def test_get_setting_reports_unknown_servants(tmp_path: Path):
    _write_json(tmp_path / "servant_info_CH.json", {"Known": {"other_name": []}})
    _write_json(
        tmp_path / "settings" / "demo.json",
        {"server": "CH", "servant_0_name": "Missing"},
    )

    detail = ScriptDataService(tmp_path).get_setting("demo")

    assert detail["validation"]["ok"] is False
    assert {
        "code": "unknown_servant",
        "field": "servant_0_name",
        "message": "Unknown servant: Missing",
    } in detail["validation"]["errors"]


def test_get_setting_reports_non_string_servant_names(tmp_path: Path):
    _write_json(tmp_path / "servant_info_CH.json", {"Known": {"other_name": []}})
    _write_json(
        tmp_path / "settings" / "demo.json",
        {"server": "CH", "servant_0_name": ["Known"]},
    )

    detail = ScriptDataService(tmp_path).get_setting("demo")

    assert detail["validation"]["ok"] is False
    assert {
        "code": "invalid_servant_name",
        "field": "servant_0_name",
        "message": "Servant name must be a string.",
    } in detail["validation"]["errors"]


def test_save_setting_writes_utf8_json_and_requires_explicit_overwrite(tmp_path: Path):
    _write_json(
        tmp_path / "servant_info_CH.json",
        {"摩根": {"other_name": [], "class": "Berserker", "SN": "309"}},
    )
    service = ScriptDataService(tmp_path)
    config = {"server": "CH", "servant_0_name": "摩根", "round1_turns": 0}

    created = service.save_setting("周回配置", config)

    assert created["name"] == "周回配置"
    assert created["config"] == config
    saved_text = (tmp_path / "settings" / "周回配置.json").read_text(encoding="utf-8")
    assert "摩根" in saved_text
    assert "\\u6469" not in saved_text
    assert not list((tmp_path / "settings").glob(".*.tmp"))

    with pytest.raises(AppError) as excinfo:
        service.save_setting("周回配置", {**config, "round1_turns": 1})

    assert excinfo.value.code == ErrorCode.DATA_FILE_CONFLICT
    overwritten = service.save_setting(
        "周回配置",
        {**config, "round1_turns": 1},
        overwrite=True,
    )
    assert overwritten["config"]["round1_turns"] == 1


def test_save_setting_rejects_invalid_config_without_creating_file(tmp_path: Path):
    service = ScriptDataService(tmp_path)

    with pytest.raises(AppError) as excinfo:
        service.save_setting("invalid", {"server": "NA"})

    assert excinfo.value.code == ErrorCode.DATA_FILE_INVALID
    assert not (tmp_path / "settings" / "invalid.json").exists()


def test_get_strategy_returns_entries_summary_and_validation(tmp_path: Path):
    _write_json(
        tmp_path / "strategy" / "brave.json",
        [{"tag": "brave", "strategy": _strategy_payload()}],
    )

    detail = ScriptDataService(tmp_path).get_strategy("brave")

    assert detail["name"] == "brave"
    assert detail["path"] == "strategy/brave.json"
    assert detail["entries"][0]["tag"] == "brave"
    assert detail["summary"] == {"entry_count": 1}
    assert detail["validation"] == {"ok": True, "errors": [], "warnings": []}


def test_get_strategy_reports_missing_card_fields(tmp_path: Path):
    payload = _strategy_payload()
    payload.pop("card2")
    _write_json(tmp_path / "strategy" / "broken.json", [{"tag": "broken", "strategy": payload}])

    detail = ScriptDataService(tmp_path).get_strategy("broken")

    assert detail["validation"]["ok"] is False
    assert {
        "code": "missing_strategy_card",
        "field": "[0].strategy.card2",
        "message": "Strategy card2 is missing.",
    } in detail["validation"]["errors"]


def test_save_strategy_validates_and_requires_explicit_overwrite(tmp_path: Path):
    service = ScriptDataService(tmp_path)
    entries = [{"tag": "宝具补刀", "strategy": _strategy_payload()}]

    created = service.save_strategy("宝具补刀", entries)

    assert created["name"] == "宝具补刀"
    assert created["entries"] == entries
    assert "宝具补刀" in (tmp_path / "strategy" / "宝具补刀.json").read_text(encoding="utf-8")

    with pytest.raises(AppError) as excinfo:
        service.save_strategy("宝具补刀", entries)

    assert excinfo.value.code == ErrorCode.DATA_FILE_CONFLICT
    changed = [{"tag": "宝具补刀2", "strategy": _strategy_payload()}]
    overwritten = service.save_strategy("宝具补刀", changed, overwrite=True)
    assert overwritten["entries"] == changed


def test_save_strategy_rejects_invalid_entries_without_creating_file(tmp_path: Path):
    service = ScriptDataService(tmp_path)

    with pytest.raises(AppError) as excinfo:
        service.save_strategy("invalid", [{"tag": "broken", "strategy": {}}])

    assert excinfo.value.code == ErrorCode.DATA_FILE_INVALID
    assert not (tmp_path / "strategy" / "invalid.json").exists()


def test_get_setting_rejects_path_traversal(tmp_path: Path):
    service = ScriptDataService(tmp_path)

    with pytest.raises(AppError) as excinfo:
        service.get_setting("../secret")

    assert excinfo.value.code == ErrorCode.DATA_FILE_NOT_FOUND


def test_lists_servants_and_masters(tmp_path: Path):
    _write_json(
        tmp_path / "servant_info_CH.json",
        {"Servant A": {"other_name": ["A"], "class": "Caster", "SN": "100", "skill_name": ["Buff"]}},
    )
    _write_json(
        tmp_path / "master_info.json",
        {"Chaldea": {"SN": 7, "skill_name": ["Heal"], "skill_type": [1]}},
    )

    service = ScriptDataService(tmp_path)

    assert service.list_servants("CH") == {
        "server": "CH",
        "servants": [
            {
                "name": "Servant A",
                "class": "Caster",
                "sn": "100",
                "aliases": ["A"],
                "skills": ["Buff"],
                "skill_types": [],
                "np_color": None,
            }
        ],
    }
    assert service.list_masters() == {
        "masters": [
            {"name": "Chaldea", "sn": 7, "skills": ["Heal"], "skill_types": [1]},
        ],
    }
