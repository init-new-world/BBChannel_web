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

