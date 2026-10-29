import json

import pytest

from tests.test_skill_variants_model import RULES
from tests.test_turn_skills_model import NODE, _run
from tests.test_turn_skills_source import _run as _source

pytestmark = pytest.mark.skipif(NODE is None, reason="Node.js is not installed.")


def test_skill_variants_share_and_reorder_sequences_with_other_named_skills():
    commands = [[name, rule[0], rule[1][-1]] for name, rule in RULES.items()]
    commands += [["Kukulkan", 2, 1, 3], ["Barghest", 3, 1], [-2, 2], 1]
    read = _run("read", value=commands)
    assert read["error"] is None
    assert read["result"] == commands
    assert _run("edit", value=commands, edit={"type": "move", "index": 0, "to": 8})["result"] == commands[1:] + commands[:1]


@pytest.mark.parametrize("named,skill,option", [(name, first, option) for name, (first, options) in RULES.items() for option in options])
def test_skill_variant_add_and_update_keep_original_string_option_codes(named, skill, option):
    for kind in ("add", "update"):
        edit = {"type": kind, "index": 0, "named": named, "skill": skill, "option": option}
        expected = ([1] if kind == "add" else []) + [[named, skill, option]]
        assert _run("edit", value=[1], edit=edit)["result"] == expected


@pytest.mark.parametrize("named", RULES)
@pytest.mark.parametrize("extra", [{"target": 1}, {"swap": [1, 4]}, {"choice": 2}, {"skill": 0}, {"skill": None}, {"option": True}])
def test_variant_edits_reject_mixed_or_invalid_parameters(named, extra):
    first, options = RULES[named]
    edit = {"type": "add", "named": named, "skill": first, "option": options[0], **extra}
    assert _run("edit", value=[1], edit=edit)["error"]


@pytest.mark.parametrize("named", RULES)
def test_variant_add_does_not_default_a_missing_skill_number(named):
    assert _run("edit", value=[1], edit={"type": "add", "named": named, "option": RULES[named][1][0]})["error"]


@pytest.mark.parametrize("named", RULES)
def test_variant_source_edits_preserve_unrelated_values_and_other_skill_types(named):
    prefix = '{"metadata":{"float":1.0,"large":9007199254740993},"round1_turn0_skill":'
    suffix = ',"round1_turn0_np":[2],"round2_extraSkill":[1.0]}'
    first, options = RULES[named]
    command = [named, first + 3, options[-1]]
    result = _source("edit", prefix + '[1]' + suffix,
                     edit={"type": "add", "named": named, "skill": command[1], "option": command[2]})
    assert result["error"] is None
    assert result["result"] == prefix + '[1,' + json.dumps(command, ensure_ascii=False, separators=(",", ":")) + ']' + suffix


@pytest.mark.parametrize("command", ['["VanGoghMiner",1.0,"Q"]', '["Dante",2e0,"A"]', '["Gyokuto",5.0,"All"]',
                                     '["Charlotte",3.0,"\u6280"]', '["Flora",9e0,"D"]'])
def test_integral_float_skill_tokens_remain_read_only(command):
    source = '{"round1_turn0_skill":[' + command + '],"metadata":1.0}'
    assert _source("inspect", source)["result"]["commands"] is None
    assert _source("edit", source, edit={"type": "add"})["error"]
    cleared = _source("edit", source, edit={"type": "clear"})
    assert json.loads(cleared["result"])["round1_turn0_skill"] == []
    assert type(json.loads(cleared["result"])["metadata"]) is float
