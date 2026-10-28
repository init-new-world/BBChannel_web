import json

import pytest

from tests.test_turn_skills_model import NODE, _run
from tests.test_turn_skills_source import _run as _source

pytestmark = pytest.mark.skipif(NODE is None, reason="Node.js is not installed.")


@pytest.mark.parametrize("skill,left,right", [(10, 1, 4), (11, 3, 6), (12, 4, 1)])
def test_order_change_commands_keep_original_position_order_on_read(skill, left, right):
    command = [skill, left, right]
    assert _run("decode", value=command)["result"] == {"skill": skill, "target": None, "swap": [left, right]}
    assert _run("read", value=[1, command, [13, 2]])["result"] == [1, command, [13, 2]]


@pytest.mark.parametrize("command", [[9, 1, 4], [13, 1, 4], [12, 1, 2], [12, 4, 6], [12, 0, 4], [12, 3, 7],
                                     [12, True, 4], [12, 1, "4"], [12, 1, 4, 5]])
def test_non_exchange_or_ambiguous_three_part_commands_remain_read_only(command):
    assert _run("decode", value=command)["result"] is None
    assert _run("read", value=[command])["error"]
    assert _run("edit", value=[command], edit={"type": "clear"})["result"] == []


@pytest.mark.parametrize("skill", [10, 11, 12])
@pytest.mark.parametrize("swap", [[1, 4], [2, 5], [3, 6], [6, 2]])
def test_exchange_edits_are_immutable_and_keep_other_commands(skill, swap):
    value = [1, [13, 2]]
    assert _run("edit", value=value, edit={"type": "add", "skill": skill, "swap": swap})["result"] == [*value, [skill, *swap]]
    assert _run("edit", value=value, edit={"type": "update", "index": 0, "skill": skill, "swap": swap})["result"] == [[skill, *swap], [13, 2]]


@pytest.mark.parametrize("edit", [
    {"type": "add", "skill": 9, "swap": [1, 4]},
    {"type": "add", "skill": 12, "swap": [1, 1]},
    {"type": "add", "skill": 12, "swap": [1, 2]},
    {"type": "add", "skill": 12, "swap": [4, 6]},
    {"type": "add", "skill": 12, "swap": [1, False]},
    {"type": "add", "skill": 12, "swap": [1, 4, 5]},
    {"type": "add", "skill": 12, "swap": None},
    {"type": "add", "skill": 12, "swap": [1, 4], "target": 2},
])
def test_invalid_exchange_edits_do_not_silently_become_ordinary_skills(edit):
    assert _run("edit", value=[1], edit=edit)["error"]


def test_exchange_reordering_only_replaces_the_selected_skill_value():
    prefix = '{"round1_turn0_np":[2],"metadata":{"float":1.0,"large":9007199254740993},"round1_turn0_skill":'
    suffix = ',"round2_extraSkill":[[13,6]]}'
    source = prefix + '[[12,4,1],2]' + suffix
    result = _source("edit", source, edit={"type": "move", "index": 0, "to": 1})
    assert result["error"] is None
    assert result["result"] == prefix + '[2,[12,4,1]]' + suffix


@pytest.mark.parametrize("sequence", ['[[12.0,1,4]]', '[[12,1.0,4]]', '[[12,1,4e0]]'])
def test_exchange_source_float_tokens_never_become_editable(sequence):
    source = '{"round1_turn0_skill":' + sequence + '}'
    assert _source("inspect", source)["result"]["commands"] is None
    assert _source("edit", source, edit={"type": "add"})["error"]
    assert json.loads(_source("edit", source, edit={"type": "clear"})["result"])["round1_turn0_skill"] == []
