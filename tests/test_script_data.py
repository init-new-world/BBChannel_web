import json
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from webapp.app import create_app
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


def test_strategy_validation_rejects_non_boolean_breakpoints(tmp_path: Path):
    strategy = _strategy_payload()
    strategy["breakpoint"] = [False, "false"]
    _write_json(tmp_path / "strategy" / "invalid.json", [{"tag": "Invalid", "strategy": strategy}])
    detail = ScriptDataService(tmp_path).get_strategy("invalid")
    assert detail["validation"]["ok"] is False
    assert any(error["code"] == "invalid_strategy_breakpoint" for error in detail["validation"]["errors"])


@pytest.mark.parametrize(("field", "value", "code"), [
    ("type", True, "invalid_strategy_card_type"),
    ("type", 3, "invalid_strategy_card_type"),
    ("type", "1", "invalid_strategy_card_type"),
    ("criticalStar", True, "invalid_strategy_critical_star"),
    ("criticalStar", -1, "invalid_strategy_critical_star"),
    ("criticalStar", 11, "invalid_strategy_critical_star"),
    ("criticalStar", float("nan"), "invalid_strategy_critical_star"),
    ("criticalStar", "5", "invalid_strategy_critical_star"),
    ("more_or_less", 1, "invalid_strategy_star_comparison"),
    ("more_or_less", "false", "invalid_strategy_star_comparison"),
])
def test_strategy_card_validation_rejects_invalid_values(tmp_path, field, value, code):
    strategy = _strategy_payload()
    strategy["card2"][field] = value
    _write_json(tmp_path / "servant_info_CH.json", {})
    _write_json(tmp_path / "strategy" / "invalid.json", [{"tag": "Invalid", "strategy": strategy}])
    _write_json(tmp_path / "settings" / "invalid.json", {
        "server": "CH", "round1_turns": 1, "round1_turn0_strategy": [strategy],
    })
    service = ScriptDataService(tmp_path)
    for validation in (service.get_strategy("invalid")["validation"],
                       service.get_setting_plan("invalid")["validation"]):
        assert validation["ok"] is False
        assert any(error["code"] == code for error in validation["errors"])
    with pytest.raises(AppError) as error:
        service.save_strategy("invalid-copy", [{"tag": "Invalid", "strategy": strategy}])
    assert error.value.code == ErrorCode.DATA_FILE_INVALID


@pytest.mark.parametrize(("card_type", "preferences"), [
    (0, []), (0, [True]), (0, ["1"]), (0, [4]),
    (1, []), (1, [1]), (1, ["4B"]), (1, ["1X"]), (1, ["S-1"]), (1, ["1BS"]),
])
def test_strategy_card_validation_rejects_invalid_preferences(tmp_path, card_type, preferences):
    strategy = _strategy_payload()
    strategy["card1"].update({"type": card_type, "cards": preferences})
    service = ScriptDataService(tmp_path)
    with pytest.raises(AppError) as error:
        service.save_strategy("invalid", [{"tag": "Invalid", "strategy": strategy}])
    errors = error.value.details["validation"]["errors"]
    assert any(issue["code"] == "invalid_strategy_card_preferences" for issue in errors)


def test_strategy_card_validation_accepts_composite_codes_and_fractional_threshold(tmp_path):
    strategy = _strategy_payload()
    strategy["card1"]["cards"] = [1, 2, 3]
    strategy["card2"].update({"cards": ["1B", "S0", "3QS12"], "criticalStar": 4.5})
    detail = ScriptDataService(tmp_path).save_strategy("valid", [{"tag": "Valid", "strategy": strategy}])
    assert detail["validation"]["ok"] is True


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
            "Servant A": {
                "other_name": [],
                "class": "Caster",
                "SN": "100",
                "NPcolor": "A",
            },
            "Support B": {
                "other_name": ["B"],
                "class": "Rider",
                "SN": "101",
                "NPcolor": "Q",
            },
        },
    )
    _write_json(tmp_path / "master_info.json", {"Chaldea": {"SN": 7}})
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
            "specialKeys": [
                [
                    r"D:\old\[Quick]W1920H1080DXL100DXR300DYT200DYB500CON85.png"
                ]
            ],
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
        {
            "slot": 0,
            "name": "Servant A",
            "canonical_name": "Servant A",
            "class": "Caster",
            "active": True,
            "used": True,
            "sn": "100",
            "np_color": "A",
        },
        {
            "slot": 1,
            "name": "B",
            "canonical_name": "Support B",
            "class": "Rider",
            "active": True,
            "used": True,
            "sn": "101",
            "np_color": "Q",
        },
        {
            "slot": 2,
            "name": None,
            "canonical_name": None,
            "class": None,
            "active": False,
            "used": False,
            "sn": None,
            "np_color": None,
        },
        {
            "slot": 3,
            "name": None,
            "canonical_name": None,
            "class": None,
            "active": False,
            "used": False,
            "sn": None,
            "np_color": None,
        },
        {
            "slot": 4,
            "name": None,
            "canonical_name": None,
            "class": None,
            "active": False,
            "used": False,
            "sn": None,
            "np_color": None,
        },
        {
            "slot": 5,
            "name": None,
            "canonical_name": None,
            "class": None,
            "active": False,
            "used": False,
            "sn": None,
            "np_color": None,
        },
    ]
    assert plan["master"] == {"equip": 7, "name": "Chaldea", "sex": 1}
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
    assert plan["special_keys"] == [
        {
            "code": "S0",
            "template_name": "[Quick]W1920H1080DXL100DXR300DYT200DYB500CON85.png",
            "template_path": "special_keys/[Quick]W1920H1080DXL100DXR300DYT200DYB500CON85.png",
            "threshold": 0.85,
            "source_width": 1920,
            "source_height": 1080,
            "left": 100,
            "right": 300,
            "top": 200,
            "bottom": 500,
        }
    ]


def test_get_setting_plan_normalizes_assist_criteria(tmp_path: Path):
    _write_json(
        tmp_path / "servant_info_CH.json",
        {
            "Support": {
                "other_name": ["Support Alias"],
                "SN": "314",
                "class": "Caster",
            }
        },
    )
    _write_json(
        tmp_path / "settings" / "demo.json",
        {
            "server": "CH",
            "servant_3_name": "Support Alias",
            "assistMode": "从者礼装",
            "assistIdx": 3,
            "allNotSkip": 0,
            "assistEquip": ["Event CE", None, "Bond CE"],
            "fullEquip": 1,
            "onlyFriendAssist": 0,
            "NPlevel": 2,
            "servantLevel": 90,
            "skillsLevel": [10, 9, 8, 0, 0, 0],
            "scrollLimit": 0.96,
            "intervalAFswipeAssist": 0.7,
            "noGrandRefresh": 1,
            "jbType": "NP50",
            "assistTags": [
                r"D:\old\assist_tags\[Guild]W1920H1080DXL100DXR300DYT200DYB500CON85.png"
            ],
        },
    )

    plan = ScriptDataService(tmp_path).get_setting_plan("demo")

    assert plan["assist"] == {
        "mode": "从者礼装",
        "slot": 3,
        "servant_name": "Support Alias",
        "servant_canonical_name": "Support",
        "servant_sn": "314",
        "servant_class": "Caster",
        "equip_names": ["Event CE", "Bond CE"],
        "full_limit_break": True,
        "friend_only": False,
        "np_level": 2,
        "servant_level": 90,
        "skill_levels": [10, 9, 8],
        "append_skill_levels": [0, 0, 0, 0, 0],
        "scroll_limit": 0.96,
        "interval_after_swipe": 0.7,
        "no_grand_refresh": True,
        "bond_equip_type": "NP50",
        "all_not_skip": False,
        "tags": [
            {
                "template_name": "[Guild]W1920H1080DXL100DXR300DYT200DYB500CON85.png",
                "template_path": "assist/assist_tags/[Guild]W1920H1080DXL100DXR300DYT200DYB500CON85.png",
                "threshold": 0.85,
                "source_width": 1920,
                "source_height": 1080,
                "left": 100,
                "right": 300,
                "top": 200,
                "bottom": 500,
            }
        ],
    }


@pytest.mark.parametrize("levels", [
    [10, 9, 8, 0, 10, 0, 8, 9], [0, 0, 0, 5, 6, 7], [1, 2, 3], [],
])
def test_assist_plan_preserves_append_skill_requirements(tmp_path: Path, levels):
    _write_json(tmp_path / "servant_info_CH.json", {})
    _write_json(tmp_path / "settings" / "demo.json", {"server": "CH", "skillsLevel": levels})
    plan = ScriptDataService(tmp_path).get_setting_plan("demo")
    assert plan["validation"]["ok"]
    assert plan["assist"]["append_skill_levels"] == (levels[3:] + [0] * 5)[:5]


@pytest.mark.parametrize("levels", ["10/10/10", [True, 0, 0], [11], [-1], [1.5], [0] * 9])
def test_assist_plan_rejects_invalid_skill_requirements(tmp_path: Path, levels):
    _write_json(tmp_path / "servant_info_CH.json", {})
    _write_json(tmp_path / "settings" / "demo.json", {"server": "CH", "skillsLevel": levels})
    plan = ScriptDataService(tmp_path).get_setting_plan("demo")
    assert not plan["validation"]["ok"]
    assert any(issue["field"] == "skillsLevel" for issue in plan["validation"]["errors"])


def test_cntw_assist_append_layout_rejects_unavailable_slots(tmp_path: Path):
    _write_json(tmp_path / "servant_info_CNTW.json", {})
    _write_json(tmp_path / "settings" / "demo.json", {"server": "CNTW", "skillsLevel": [0] * 6 + [10, 0]})
    service = ScriptDataService(tmp_path)
    plan = service.get_setting_plan("demo")
    assert not plan["validation"]["ok"]
    assert plan["validation"]["errors"][0]["code"] == "unsupported_append_skill"
    _write_json(tmp_path / "settings" / "demo.json", {"server": "CNTW", "skillsLevel": [1, 2, 3, 4, 5, 6]})
    assert service.get_setting_plan("demo")["assist"]["append_skill_levels"] == [4, 5, 6]


@pytest.mark.parametrize("confidence,expected", [("01", 0.01), ("005", 0.005), ("805", 0.805), ("85", 0.85)])
def test_special_key_threshold_preserves_leading_zeroes(confidence, expected):
    keys = ScriptDataService._plan_special_keys({"specialKeys": [
        f"[Quick]W1280H720DXL-10DXR10DYT-20DYB20CON{confidence}.png",
    ]})
    assert keys[0]["threshold"] == expected


@pytest.mark.parametrize("keys", [
    "broken.png", [None], [[]], ["broken.png"],
    ["W0H720DXL0DXR20DYT0DYB20CON8.png"],
    ["W1280H-720DXL0DXR20DYT0DYB20CON8.png"],
    ["W1280H720DXL20DXR0DYT0DYB20CON8.png"],
    ["W1280H720DXL0DXR20DYT20DYB20CON8.png"],
])
def test_invalid_special_keys_are_reported_instead_of_crashing_plan(tmp_path: Path, keys):
    _write_json(tmp_path / "servant_info_CH.json", {})
    _write_json(tmp_path / "settings" / "demo.json", {"server": "CH", "specialKeys": keys})
    plan = ScriptDataService(tmp_path).get_setting_plan("demo")
    assert not plan["validation"]["ok"]
    assert plan["validation"]["errors"][0]["field"] == "specialKeys"
    assert plan["special_keys"] == []


def test_get_setting_plan_flattens_grand_assist_equip_groups(tmp_path: Path):
    _write_json(tmp_path / "servant_info_CH.json", {})
    _write_json(
        tmp_path / "settings" / "grand.json",
        {
            "server": "CH",
            "assistMode": "冠位助战",
            "assistEquip": [
                ["Holmes", "Bond CE", "Tea Time"],
                None,
                ["Tea Time", "Event CE", "Holmes"],
            ],
        },
    )

    plan = ScriptDataService(tmp_path).get_setting_plan("grand")

    assert plan["assist"]["equip_names"] == [
        "Holmes",
        "Bond CE",
        "Tea Time",
        "Event CE",
    ]
    assert plan["assist"]["equip_slots"] == {
        "normal": ["Holmes", "Bond CE", "Tea Time"],
        "kizuna": [],
        "houshuu": ["Tea Time", "Event CE", "Holmes"],
    }


def test_get_setting_plan_normalizes_run_options(tmp_path: Path):
    _write_json(tmp_path / "servant_info_CH.json", {})
    _write_json(
        tmp_path / "settings" / "demo.json",
        {
            "server": "CH",
            "clearAP": 1,
            "allowOtherApple": 0,
            "firstBattleSet": 1,
            "intervalBF": 0.2,
            "intervalBFchooseCard": 0.6,
            "intervalAF": 0.3,
            "randomTime": 0.4,
            "randomTouch": 1,
            "noChain": 1,
            "noSpeedupSkill": 1,
            "fullFriendshipStop": 1,
            "ignoreFriendship": "1x35",
            "dropStopNum": 2,
            "dropImage": "assets/drop/item.png",
            "gameCrushRestart": 1,
            "stuckRestart": 1,
            "checkStuckInterval": 45,
            "addFriend": 1,
        },
    )

    plan = ScriptDataService(tmp_path).get_setting_plan("demo")

    assert plan["run"] == {
        "clear_ap": True,
        "allow_other_apple": False,
        "first_battle_set": True,
        "interval_before_fight": 0.2,
        "interval_before_operation": 0.2,
        "interval_before_choose_card": 0.6,
        "interval_after_fight": 0.3,
        "interval_after_operation": 0.3,
        "random_time": 0.4,
        "random_touch": True,
        "no_chain": True,
        "no_speedup_skill": True,
        "full_friendship_stop": True,
        "ignored_friendship_slots": [1, 3, 5],
        "drop_stop_num": 2,
        "drop_image": "assets/drop/item.png",
        "game_crash_restart": True,
        "stuck_restart": True,
        "check_stuck_interval": 45,
        "add_friend": True,
    }


@pytest.mark.parametrize("value,expected", [
    ("", []), ("x1035-6", [1, 3, 5]), (["2", None, "5", 6], [2, 5]),
    (["1", 3.8, True, False], [1, 3, 1]),
    (None, []), (False, []), ({"1": True}, []),
])
def test_ignored_friendship_positions_follow_original_client_parsing(tmp_path: Path, value, expected):
    _write_json(tmp_path / "servant_info_CH.json", {})
    _write_json(tmp_path / "settings" / "demo.json", {"server": "CH", "ignoreFriendship": value})
    plan = ScriptDataService(tmp_path).get_setting_plan("demo")
    assert plan["run"]["ignored_friendship_slots"] == expected


def test_get_setting_rejects_invalid_stuck_watchdog_interval(tmp_path: Path):
    _write_json(tmp_path / "servant_info_CH.json", {})
    _write_json(
        tmp_path / "settings" / "demo.json",
        {
            "server": "CH",
            "stuckRestart": 1,
            "checkStuckInterval": 0,
        },
    )

    detail = ScriptDataService(tmp_path).get_setting("demo")

    assert detail["validation"]["ok"] is False
    assert {
        "code": "invalid_stuck_interval",
        "field": "checkStuckInterval",
        "message": "Stuck watchdog interval must be between 1 and 600 seconds.",
    } in detail["validation"]["errors"]


def test_get_setting_rejects_invalid_assist_tag_metadata(tmp_path: Path):
    _write_json(tmp_path / "servant_info_CH.json", {})
    _write_json(
        tmp_path / "settings" / "demo.json",
        {
            "server": "CH",
            "assistTags": [
                r"D:\old\assist_tags\[Broken]W0H1080DXL300DXR100DYT20DYB20CON85.png"
            ],
        },
    )

    detail = ScriptDataService(tmp_path).get_setting("demo")

    assert detail["validation"]["ok"] is False
    assert {
        "code": "invalid_assist_tags",
        "field": "assistTags",
        "message": "assistTags[0] has invalid metadata.",
    } in detail["validation"]["errors"]


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


def test_delete_setting_removes_only_resolved_json_file(tmp_path: Path):
    _write_json(tmp_path / "settings" / "demo.json", {"server": "CH"})
    service = ScriptDataService(tmp_path)

    result = service.delete_setting("demo")

    assert result == {"name": "demo", "path": "settings/demo.json", "deleted": True}
    assert not (tmp_path / "settings" / "demo.json").exists()
    with pytest.raises(AppError) as excinfo:
        service.delete_setting("demo")
    assert excinfo.value.code == ErrorCode.DATA_FILE_NOT_FOUND


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


def test_delete_strategy_removes_resolved_json_file(tmp_path: Path):
    _write_json(tmp_path / "strategy" / "brave.json", [])
    service = ScriptDataService(tmp_path)

    result = service.delete_strategy("brave.json")

    assert result == {"name": "brave", "path": "strategy/brave.json", "deleted": True}
    assert not (tmp_path / "strategy" / "brave.json").exists()


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


@pytest.mark.parametrize(
    "replace_value",
    [
        [],
        "invalid",
        {"0": 4},
        {"7": 4},
        {"1": 0},
        {"1": 7},
        {"1": True},
        {"1": "4"},
    ],
)
def test_setting_validation_rejects_invalid_turn_replace(tmp_path: Path, replace_value):
    _write_json(tmp_path / "servant_info_CH.json", {})
    service = ScriptDataService(tmp_path)
    with pytest.raises(AppError) as excinfo:
        service.save_setting(
            "invalid-replace",
            {
                "server": "CH",
                "round1_turns": 1,
                "round1_turn0_replace": replace_value,
            },
        )
    assert excinfo.value.code == ErrorCode.DATA_FILE_INVALID
    errors = excinfo.value.details["validation"]["errors"]
    assert any(issue["code"] == "invalid_turn_replace" for issue in errors)


def test_calculate_turn_replacements_arash_chen_gong_and_miss_crane(tmp_path: Path):
    _write_json(
        tmp_path / "servant_info_CH.json",
        {
            "阿拉什": {"SN": "16", "class": "Archer", "other_name": ["大英雄"]},
            "陈宫": {"SN": "263", "class": "Caster", "other_name": []},
            "鹤小姐": {"SN": "308", "class": "Caster", "other_name": []},
            "阿尔托莉雅·卡斯特": {"SN": "284", "class": "Caster", "other_name": ["C呆"]},
            "奥伯龙": {"SN": "316", "class": "Pretender", "other_name": []},
            "诸葛孔明〔埃尔梅罗Ⅱ世〕": {"SN": "37", "class": "Caster", "other_name": ["孔明"]},
        },
    )
    service = ScriptDataService(tmp_path)
    config = {
        "server": "CH",
        "servant_0_name": "大英雄",
        "servant_1_name": "陈宫",
        "servant_2_name": "鹤小姐",
        "servant_3_name": "C呆",
        "servant_4_name": "奥伯龙",
        "servant_5_name": "孔明",
        "assistIdx": 3,
        "round1_turns": 1,
        "round1_turn0_skill": [],
        "round1_turn0_np": [1],
        "round2_turns": 1,
        "round2_turn0_skill": [],
        "round2_turn0_np": [3, 2],
    }

    r1 = service.calculate_turn_replacements(
        {k: v for k, v in config.items() if not k.startswith("round2_")},
        target_round=1,
        target_turn=0,
    )
    assert r1["target_field"] == "round1_turn0_replace"
    assert r1["replacements"] == {"1": 4, "4": 5, "5": 6, "6": None}
    assert r1["used_servants"] == [0, 1, 2]

    r2 = service.calculate_turn_replacements(config, target_round=2, target_turn=0)
    assert r2["target_field"] == "round2_turn0_replace"
    # On W2T0:
    # Party entering W2T0 has slots [4(C呆), 2(陈宫), 3(鹤小姐), 5(奥伯龙), 6(孔明), None].
    # NP [3, 2]:
    # - 3 (鹤小姐) retreats to backline -> sacrifice_lst=[3], replace_lst=[4], resurrection_lst=[3]
    # - 2 (陈宫) sacrifices slot 1 -> sacrifice_lst=[3, 1], replace_lst=[4, 5]
    # Deal with death:
    # - Slot 3 (resurrection) gets slot 4 (奥伯龙); slot 1 (permanent sacrifice) gets slot 5 (孔明);
    # - Slot 3 (鹤小姐) moves to backline slot 4, slot 5 becomes None.
    assert r2["replacements"] == {"1": 5, "3": 4, "4": 3, "5": None}
    assert r2["used_servants"] == [0, 1, 2, 4, 5]


def test_calculate_turn_replacements_tutankhamun_chloe_habetrot_guts_and_swap(tmp_path: Path):
    _write_json(
        tmp_path / "servant_info_CH.json",
        {
            "图坦卡蒙": {"SN": "425", "class": "Archer", "other_name": []},
            "克洛伊·冯·爱因兹贝伦(Avenger)": {"SN": "388", "class": "Avenger", "other_name": ["水小黑"]},
            "哈贝特洛特": {"SN": "317", "class": "Rider", "other_name": ["哈贝喵"]},
            "奥伯龙": {"SN": "316", "class": "Pretender", "other_name": []},
            "杀生院祈荒": {"SN": "167", "class": "Alterego", "other_name": []},
        },
    )
    service = ScriptDataService(tmp_path)

    # Tutankhamun using S3 (skill 3) before NP does NOT sacrifice at NP end of turn;
    # Summer Chloe S2 (skill [5, 1]) retreats to backline;
    # Habetrot S3 (skill [9, 1]) sacrifices herself.
    config = {
        "server": "CH",
        "servant_0_name": "图坦卡蒙",
        "servant_1_name": "水小黑",
        "servant_2_name": "哈贝喵",
        "servant_3_name": "奥伯龙",
        "servant_4_name": "杀生院祈荒",
        "servant_5_name": "",
        "assistIdx": 3,
        "round1_turns": 1,
        "round1_turn0_skill": [3, [5, 1], [9, 1]],
        "round1_turn0_np": [1],
    }
    res = service.calculate_turn_replacements(config, target_round=1, target_turn=0)
    # Slot 1 (Tutankhamun) stays alive because S3 (skill 3) was used;
    # Slot 2 (Summer Chloe) retreats and swaps with Slot 4 (Oberon);
    # Slot 3 (Habetrot) sacrifices and is replaced by Slot 5 (Kiara);
    # Summer Chloe moves to backline Slot 4, Slot 5 becomes None.
    assert res["replacements"] == {"2": 4, "3": 5, "4": 2, "5": None}
    assert res["used_servants"] == [0, 1, 2, 4]

    # With Guts on Habetrot (slot 2 -> index 2), Habetrot survives S3, and if Tutankhamun does NOT use S3, he sacrifices.
    config_no_s3 = {
        **config,
        "round1_turn0_skill": [[12, 1, 5], [9, 1]],
        "round1_turn0_np": [1],
    }
    res_guts = service.calculate_turn_replacements(
        config_no_s3,
        target_round=1,
        target_turn=0,
        will_nums=[0, 0, 1, 0, 0, 0],
        death_slots=[2],
    )
    # [12, 1, 5] swapped slot 1 (0) and slot 5 (4), so both 0 and 4 are in used_servants;
    # Slot 2 had manual death_slots=[2], replaced by slot 4 (Oberon);
    # Slot 3 (Habetrot) consumed 1 Guts and survived!
    assert res_guts["replacements"] == {"2": 4, "4": 5, "5": None}
    assert res_guts["used_servants"] == [0, 1, 2, 4]


def test_calculate_turn_replacements_endpoint_and_chen_gong_error(tmp_path: Path):
    assets_dir = tmp_path / "assets"
    data_dir = tmp_path / "data"
    assets_dir.mkdir()
    _write_json(
        data_dir / "servant_info_CH.json",
        {
            "陈宫": {"SN": "263", "class": "Caster", "other_name": []},
            "奥伯龙": {"SN": "316", "class": "Pretender", "other_name": []},
        },
    )
    client = TestClient(create_app(assets_dir=assets_dir, data_dir=data_dir))

    # Chen Gong alone on frontline raises 400 data_file_invalid
    bad_response = client.post(
        "/api/settings/calculate-turn-replace",
        json={
            "config": {
                "server": "CH",
                "servant_0_name": "陈宫",
                "round1_turns": 1,
                "round1_turn0_np": [1],
            },
            "target_round": 1,
            "target_turn": 0,
        },
    )
    assert bad_response.status_code == 400
    assert bad_response.json()["error"]["code"] == "data_file_invalid"

    # Valid Chen Gong sacrifice with ally in slot 2 and backline in slot 4
    ok_response = client.post(
        "/api/settings/calculate-turn-replace",
        json={
            "source": json.dumps(
                {
                    "server": "CH",
                    "servant_0_name": "陈宫",
                    "servant_1_name": "奥伯龙",
                    "servant_3_name": "奥伯龙",
                    "assistIdx": 3,
                    "round1_turns": 1,
                    "round1_turn0_np": [1],
                }
            ),
            "target_round": 1,
            "target_turn": 0,
        },
    )
    assert ok_response.status_code == 200
    payload = ok_response.json()
    assert payload["target_field"] == "round1_turn0_replace"
    assert payload["replacements"] == {"2": 4, "4": None}
    assert payload["used_servants"] == [0, 1]


def test_pre_run_report_checks_frontline_subtitles_and_special_assist_servants(tmp_path: Path):
    assets_dir = tmp_path / "assets"
    data_dir = tmp_path / "data"
    assets_dir.mkdir()
    _write_json(
        data_dir / "servant_info_CH.json",
        {
            "妖精骑士兰斯洛特": {"SN": "312", "class": "Lancer", "other_name": ["妖兰"]},
            "托勒密": {"SN": "391", "class": "Archer", "other_name": []},
            "U－奥尔加玛丽": {"SN": "430", "class": "Beast", "other_name": ["总统"]},
        },
    )
    _write_json(
        data_dir / "settings" / "melusine.json",
        {
            "server": "CH",
            "servant_0_name": "妖兰",
            "servant_1_name": "托勒密",
            "servant_2_name": "",
            "assistIdx": 0,
            "assistMode": "从者礼装",
            "assistEquip": [["黑之圣杯"], [], ["迦勒底午餐时光"]],
            "onlyFriendAssist": 1,
            "fullEquip": 1,
            "NPlevel": 2,
            "servantLevel": 100,
            "skillsLevel": [10, 10, 10, 0, 10, 0, 0, 0],
            "round1_turns": 1,
        },
    )
    client = TestClient(create_app(assets_dir=assets_dir, data_dir=data_dir))

    get_resp = client.get("/api/settings/melusine/pre-run-report")
    assert get_resp.status_code == 200
    report = get_resp.json()
    assert report["frontline_ready"] is False
    assert report["missing_frontline_slots"] == [2]
    assert report["frontline_warning"] == "编队前排不足3人，是否仍然开始脚本？"
    assert report["subtitle_warning_applicable"] is True
    assert report["subtitle_tip_image"] == "ui/closesub.png"
    assist = report["assist_report"]
    assert assist["server_label"] == "简中服"
    assert assist["servant_display"] == "妖兰"
    assert assist["servant_canonical_name"] == "妖精骑士兰斯洛特"
    assert assist["equip_slots_display"] == ["黑之圣杯", "未指定", "迦勒底午餐时光"]
    assert assist["friend_only_effective"] is True
    assert assist["full_limit_break_effective"] is True
    assert assist["servant_constraints_effective"] is True
    assert assist["check_np_color"] is True
    assert assist["check_servant_name"] is False
    assert assist["special_filter_options"] == ["arts", "buster"]
    assert assist["default_special_filter"] == "arts"

    # Preview endpoint with U-Olga Marie on JP and CE-only mode warnings
    olga_resp = client.post(
        "/api/settings/pre-run-report",
        json={
            "config": {
                "server": "JP",
                "servant_0_name": "总统",
                "servant_1_name": "托勒密",
                "servant_2_name": "妖兰",
                "assistIdx": 0,
                "assistMode": "冠位助战",
            }
        },
    )
    assert olga_resp.status_code == 200
    olga = olga_resp.json()
    assert olga["frontline_ready"] is True
    assert olga["missing_frontline_slots"] == []
    assert olga["subtitle_warning_applicable"] is False
    assert olga["assist_report"]["check_servant_name"] is True
    assert olga["assist_report"]["special_filter_options"] == ["u_olga", "olga"]
    assert olga["assist_report"]["default_special_filter"] == "u_olga"
    assert olga["assist_report"]["full_limit_break_effective"] is False
    assert olga["assist_report"]["full_limit_break_warning"] == "(礼装未指定不生效)"

    ce_only_resp = client.post(
        "/api/settings/pre-run-report",
        json={
            "config": {
                "server": "CNTW",
                "assistIdx": 0,
                "servant_0_name": "总统",
                "assistMode": "仅礼装",
                "assistEquip": ["黑之圣杯"],
            }
        },
    )
    assert ce_only_resp.status_code == 200
    ce_only = ce_only_resp.json()["assist_report"]
    assert ce_only["server_label"] == "繁中服"
    assert ce_only["servant_display"] == "未指定"
    assert ce_only["friend_only_effective"] is False
    assert ce_only["friend_only_warning"] == "(从者未指定不生效)"
    assert ce_only["servant_constraints_effective"] is False
    assert ce_only["servant_constraints_warning"] == "注意以下设置在从者未指定时不生效"
    assert ce_only["append_skill_levels"] == [0, 0, 0]
    assert ce_only["default_special_filter"] == "any"


def test_setting_plan_validates_and_exposes_screen_rotation(tmp_path: Path):
    data_dir = tmp_path / "data"
    _write_json(data_dir / "servant_info_CH.json", {})
    _write_json(
        data_dir / "settings" / "rotated.json",
        {
            "server": "CH",
            "round1_turns": 1,
            "screenRotation": 270,
        },
    )
    service = ScriptDataService(data_dir)
    plan = service.get_setting_plan("rotated")
    assert plan["screen_rotation"] == 270

    invalid_angle = service._validate_setting({"server": "CH", "screenRotation": 45})
    assert invalid_angle["ok"] is False
    assert any(item["code"] == "invalid_screen_rotation" for item in invalid_angle["errors"])

    invalid_bool = service._validate_setting({"server": "CH", "screenRotation": True})
    assert invalid_bool["ok"] is False
    assert any(item["code"] == "invalid_screen_rotation" for item in invalid_bool["errors"])


def test_setting_plan_validates_and_exposes_turn_and_extra_conditions(tmp_path: Path):
    data_dir = tmp_path / "data"
    _write_json(data_dir / "servant_info_CH.json", {})
    condition_entry = {
        "card1": {"type": 0, "cards": [1], "criticalStar": 0, "more_or_less": True},
        "card2": {"type": 1, "cards": ["Red"], "criticalStar": 0, "more_or_less": True},
        "card3": {"type": 2, "cards": [1], "criticalStar": 0, "more_or_less": True},
        "breakpoint": [0, 0, 0],
        "colorFirst": False,
    }
    _write_json(
        data_dir / "settings" / "conditional.json",
        {
            "server": "CH",
            "round1_turns": 1,
            "round1_turn0_condition": [condition_entry],
            "round1_extraCondition": [condition_entry],
        },
    )
    service = ScriptDataService(data_dir)
    plan = service.get_setting_plan("conditional")
    assert plan["rounds"][0]["turns"][0]["condition"] == [condition_entry]
    assert plan["rounds"][0]["extra_condition"] == [condition_entry]

    invalid_cond = service._validate_setting({"server": "CH", "round1_extraCondition": "bad"})
    assert any(item["field"] == "round1_extraCondition" for item in invalid_cond["warnings"])


def test_strategy_turns_ignore_leftover_simple_np_selection_and_preserve_lead_card_order(tmp_path: Path):
    from webapp.automation.program import compile_battle_program
    from webapp.automation.strategy import select_command_cards

    data_dir = tmp_path / "data"
    _write_json(data_dir / "servant_info_CH.json", {"希耶尔": {"SN": "2300900", "class": "MoonCancer", "other_name": []}})
    strategy_entry = {
        "card1": {"type": 1, "cards": ["2B"], "criticalStar": 0, "more_or_less": True},
        "card2": {"type": 0, "cards": [2], "criticalStar": 0, "more_or_less": True},
        "card3": {"type": 1, "cards": ["2B"], "criticalStar": 0, "more_or_less": True},
        "breakpoint": [False, False],
        "colorFirst": False,
    }
    _write_json(
        data_dir / "settings" / "ciel.json",
        {
            "server": "CH",
            "servant_1_name": "希耶尔",
            "round1_turns": 1,
            "round1_turn0_np": [2],
            "round1_turn0_strategy": [strategy_entry],
        },
    )
    service = ScriptDataService(data_dir)
    program = compile_battle_program(service.get_setting_plan("ciel"))
    step = program["rounds"][0]["turns"][0]["command_phase"]["steps"][1]
    assert step["role"] == "command_card_strategy"
    assert step["preselected_nps"] == []

    cards = [
        {"slot": 1, "code": "2B", "servant_position": 2, "color": "B", "stars": 0, "available": True, "special_keys": []},
        {"slot": 2, "code": "1A", "servant_position": 1, "color": "A", "stars": 0, "available": True, "special_keys": []},
        {"slot": 3, "code": "2B", "servant_position": 2, "color": "B", "stars": 0, "available": True, "special_keys": []},
        {"slot": 4, "code": "3Q", "servant_position": 3, "color": "Q", "stars": 0, "available": True, "special_keys": []},
        {"slot": 5, "code": "1B", "servant_position": 1, "color": "B", "stars": 0, "available": True, "special_keys": []},
    ]
    selected = select_command_cards(step["strategies"], cards, preselected_nps=step["preselected_nps"])
    assert selected == [
        {"type": "face", "slot": 1, "code": "2B", "stars": 0},
        {"type": "np", "servant": 2},
        {"type": "face", "slot": 3, "code": "2B", "stars": 0},
    ]


def test_grand_assist_equip_slots_merge_appended_ui_elements_and_report_missing_templates(tmp_path: Path):
    from webapp.services.resources import ResourceService

    assets_dir = tmp_path / "assets"
    data_dir = tmp_path / "data"
    (assets_dir / "assist" / "assist_equip").mkdir(parents=True)
    (assets_dir / "assist" / "assist_equip" / "迦勒底午茶时光.png").write_bytes(b"png")
    _write_json(data_dir / "servant_info_CH.json", {"伊什塔尔": {"SN": "202000", "class": "Archer", "other_name": []}})
    _write_json(
        data_dir / "settings" / "grand_archer.json",
        {
            "server": "CH",
            "assistMode": "冠位助战",
            "assistIdx": 1,
            "servant_1_name": "伊什塔尔",
            "assistEquip": [[], None, [], "迦勒底午茶时光", "不存在的礼装"],
            "round1_turns": 1,
        },
    )
    resources = ResourceService(assets_dir, data_dir)
    service = ScriptDataService(data_dir, resources=resources)
    plan = service.get_setting_plan("grand_archer")
    assert plan["assist"]["equip_slots"] == {
        "normal": ["迦勒底午茶时光", "不存在的礼装"],
        "kizuna": [],
        "houshuu": [],
    }
    report = service.get_setting_pre_run_report("grand_archer")["assist_report"]
    assert report["equip_slots"][0] == ["迦勒底午茶时光", "不存在的礼装"]
    assert report["missing_equip_templates"] == ["不存在的礼装"]
    assert report["equip_warning"] == "缺少助战礼装模板：不存在的礼装"


def test_all_real_settings_and_strategies_in_repo_validate_and_compile_cleanly():
    from webapp.automation.program import compile_battle_program
    from webapp.services.resources import ResourceService

    project_root = Path(__file__).resolve().parents[1]
    resources = ResourceService(project_root / "assets", project_root / "data")
    service = ScriptDataService(project_root / "data", resources=resources)

    settings = service.list_settings()
    assert len(settings) >= 21
    for item in settings:
        name = item["name"]
        detail = service.get_setting(name)
        assert detail["validation"]["ok"] is True, f"{name}: {detail['validation']}"
        plan = service.get_setting_plan(name)
        program = compile_battle_program(plan)
        assert program["execution"]["battle"]["ready"] is True, f"{name}: {program['execution']}"
        report = service.get_setting_pre_run_report(name)
        assert report["assist_report"]["missing_equip_templates"] == [], f"{name}: {report['assist_report']}"

    strategies = service.list_strategies()
    assert len(strategies) >= 5
    for item in strategies:
        detail = service.get_strategy(item["name"])
        assert detail["validation"]["ok"] is True, f"{item['name']}: {detail['validation']}"


def test_pre_run_report_and_plan_assist_handle_normal_nulls_grand_ce_only_dict_and_lowercase_cntw(tmp_path: Path):
    _write_json(tmp_path / "servant_info_CNTW.json", {"Servant A": {"SN": "100", "class": "Caster", "other_name": []}})
    _write_json(
        tmp_path / "settings" / "normal_trailing_null.json",
        {
            "server": "cntw",
            "assistMode": "从者礼装",
            "assistIdx": 2,
            "servant_2_name": "Servant A",
            "assistEquip": ["CE1", "CE2", None],
            "skillsLevel": [10, 10, 10, 10, 10, 0, 10, 10],
            "round1_turns": 1,
        },
    )
    _write_json(
        tmp_path / "settings" / "grand_ce_only.json",
        {
            "server": "CH",
            "assistMode": "冠位助战仅礼装",
            "assistIdx": 2,
            "servant_2_name": "Servant A",
            "onlyFriendAssist": 1,
            "assistEquip": {"normal": ["CE1"], "kizuna": "BondCE", "houshuu": ["RewardCE"]},
            "round1_turns": 1,
        },
    )
    _write_json(tmp_path / "servant_info_CH.json", {"Servant A": {"SN": "100", "class": "Caster", "other_name": []}})
    service = ScriptDataService(tmp_path)

    normal_report = service.get_setting_pre_run_report("normal_trailing_null")
    assert normal_report["assist_report"]["equip_slots"] == [["CE1", "CE2"], [], []]
    normal_plan = service.get_setting_plan("normal_trailing_null")
    assert len(normal_plan["assist"]["append_skill_levels"]) == 3

    grand_report = service.get_setting_pre_run_report("grand_ce_only")
    assert grand_report["assist_report"]["friend_only_effective"] is False
    assert grand_report["assist_report"]["equip_slots"] == [["CE1"], ["BondCE"], ["RewardCE"]]
    grand_plan = service.get_setting_plan("grand_ce_only")
    assert grand_plan["assist"]["equip_names"] == ["CE1", "BondCE", "RewardCE"]





