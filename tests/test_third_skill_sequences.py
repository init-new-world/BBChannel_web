import json

import pytest

from tests.test_command_spell_model import NP_SPELL
from tests.test_third_skill_model import OPTIONS
from tests.test_turn_skills_model import NODE, _run
from tests.test_turn_skills_source import _run as _source

pytestmark = pytest.mark.skipif(NODE is None, reason="Node.js is not installed.")


def test_third_skill_commands_share_and_reorder_a_mixed_sequence():
    commands = [1, ["Barghest", 3, 1], ["BBDubai", 6, 0], ["Soujyuro", 9, "A"],
                ["Hakuno", 3, "R"], ["Kukulkan", 2, 1, 3], [-2, 3], [NP_SPELL, 2], [12, 1, 4]]
    read = _run("read", value=commands)
    assert read["error"] is None
    assert read["result"] == commands
    expected = commands[:1] + commands[2:] + commands[1:2]
    assert _run("edit", value=commands, edit={"type": "move", "index": 1, "to": 8})["result"] == expected


@pytest.mark.parametrize("named,option", [(name, option) for name, options in OPTIONS.items() for option in options])
def test_named_third_skill_add_and_update_keep_canonical_option_types(named, option):
    for kind, skill in (("add", 3), ("update", 9)):
        edit = {"type": kind, "index": 0, "named": named, "skill": skill, "option": option}
        expected = ([1] if kind == "add" else []) + [[named, skill, option]]
        assert _run("edit", value=[1], edit=edit)["result"] == expected


@pytest.mark.parametrize("named", OPTIONS)
@pytest.mark.parametrize("extra", [{"target": 1}, {"swap": [1, 4]}, {"choice": 2}, {"skill": 1}, {"skill": None}, {"option": True}])
def test_named_third_skill_edits_reject_mixed_or_missing_parameters(named, extra):
    edit = {"type": "add", "named": named, "skill": 3, "option": OPTIONS[named][0], **extra}
    assert _run("edit", value=[1], edit=edit)["error"]


@pytest.mark.parametrize("named", OPTIONS)
def test_named_third_skill_add_does_not_guess_a_missing_position(named):
    assert _run("edit", value=[1], edit={"type": "add", "named": named, "option": OPTIONS[named][0]})["error"]


@pytest.mark.parametrize("named", OPTIONS)
def test_third_skill_source_edits_preserve_all_unrelated_tokens(named):
    prefix = '{"metadata":{"float":1.0,"large":9007199254740993},"round1_turn0_skill":'
    suffix = ',"round1_turn0_np":[2],"round2_extraSkill":[1.0]}'
    option = OPTIONS[named][-1]
    command = json.dumps([named, 6, option], separators=(",", ":"))
    result = _source("edit", prefix + '[1]' + suffix,
                     edit={"type": "add", "named": named, "skill": 6, "option": option})
    assert result["error"] is None
    assert result["result"] == prefix + '[1,' + command + ']' + suffix


@pytest.mark.parametrize("command", ['["Barghest",3.0,0]', '["Barghest",3,0.0]', '["BBDubai",6,1e0]',
                                     '["Soujyuro",9e0,"Q"]', '["Hakuno",3.0,"T"]'])
def test_integral_float_tokens_in_third_skill_commands_stay_read_only(command):
    source = '{"round1_turn0_skill":[' + command + '],"metadata":1.0}'
    assert _source("inspect", source)["result"]["commands"] is None
    assert _source("edit", source, edit={"type": "add"})["error"]
    cleared = _source("edit", source, edit={"type": "clear"})
    assert json.loads(cleared["result"])["round1_turn0_skill"] == []
    assert type(json.loads(cleared["result"])["metadata"]) is float
