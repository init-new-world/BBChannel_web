import json

import pytest

from tests.test_command_spell_model import NP_SPELL
from tests.test_turn_skills_model import NODE, _run
from tests.test_turn_skills_source import _run as _source

pytestmark = pytest.mark.skipif(NODE is None, reason="Node.js is not installed.")


def test_kukulkan_commands_can_share_and_reorder_a_sequence_with_other_command_domains():
    commands = [1, ["Kukulkan", 2, 1, 3], [-2, 3], [NP_SPELL, 2], [12, 1, 4]]
    assert _run("read", value=commands)["result"] == commands
    assert _run("edit", value=commands, edit={"type": "move", "index": 1, "to": 4})["result"] == [1, [-2, 3], [NP_SPELL, 2], [12, 1, 4], ["Kukulkan", 2, 1, 3]]


@pytest.mark.parametrize("edit,expected", [
    ({"type": "add", "named": "Kukulkan", "skill": 1, "option": 0}, [1, ["Kukulkan", 1, 0]]),
    ({"type": "update", "index": 0, "named": "Kukulkan", "skill": 2, "option": 1, "target": 3}, [["Kukulkan", 2, 1, 3]]),
])
def test_kukulkan_edits_keep_original_canonical_name_and_parameter_order(edit, expected):
    assert _run("edit", value=[1], edit=edit)["result"] == expected


@pytest.mark.parametrize("edit", [
    {"type": "add", "named": "Kukulkan", "skill": 1, "option": True},
    {"type": "add", "named": "Kukulkan", "skill": 2, "option": 1},
    {"type": "add", "named": "Kukulkan", "option": 1},
    {"type": "update", "index": 0, "named": "Kukulkan", "option": 1},
    {"type": "add", "named": "Kukulkan", "skill": 1, "option": 1, "swap": [1, 4]},
    {"type": "add", "named": "Kukulkan", "skill": 1, "option": 1, "choice": 2},
    {"type": "add", "named": "Future", "skill": 1, "option": 1},
    {"type": "add", "skill": 1, "option": 1},
])
def test_kukulkan_edits_never_silently_become_another_command_type(edit):
    assert _run("edit", value=[1], edit=edit)["error"]


def test_kukulkan_source_edits_only_replace_the_selected_skill_value():
    prefix = '{"metadata":{"float":1.0,"large":9007199254740993},"round1_turn0_skill":'
    suffix = ',"round1_turn0_np":[2]}'
    result = _source("edit", prefix + '[1]' + suffix,
                     edit={"type": "add", "named": "Kukulkan", "skill": 2, "option": 1, "target": 3})
    assert result["error"] is None
    assert result["result"] == prefix + '[1,["Kukulkan",2,1,3]]' + suffix


@pytest.mark.parametrize("command", ['["Kukulkan",1.0,0]', '["Kukulkan",1,0.0]', '["Kukulkan",2,1,3e0]'])
def test_float_tokens_in_kukulkan_commands_remain_read_only(command):
    source = '{"round1_turn0_skill":[' + command + '],"metadata":1.0}'
    assert _source("inspect", source)["result"]["commands"] is None
    assert _source("edit", source, edit={"type": "add"})["error"]
    cleared = _source("edit", source, edit={"type": "clear"})
    assert json.loads(cleared["result"])["round1_turn0_skill"] == []
    assert type(json.loads(cleared["result"])["metadata"]) is float
