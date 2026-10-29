import json

import pytest

from tests.test_turn_skills_model import NODE, _run
from tests.test_turn_skills_source import _run as _source

pytestmark = pytest.mark.skipif(NODE is None, reason="Node.js is not installed.")


def test_hakuno_first_and_third_skills_can_share_a_sequence_without_confusing_their_parameter_types():
    commands = [["Hakuno", 1, [["1B", "1B"], ["S0", "2AS1"]]], ["Hakuno", 3, "R"],
                ["Kukulkan", 2, 1, 3], ["Flora", 3, "D"], [-2, 1], 1]
    read = _run("read", value=commands)
    assert read["error"] is None
    assert read["result"] == commands
    assert _run("edit", value=commands, edit={"type": "move", "index": 0, "to": 5})["result"] == commands[1:] + commands[:1]


@pytest.mark.parametrize("skill", [1, 4, 7])
@pytest.mark.parametrize("needs", [[], [[]], [["1B", "1B"], ["S0", "2AS10"]]])
def test_hakuno_needs_add_and_update_keep_exact_original_triples(skill, needs):
    for kind in ("add", "update"):
        edit = {"type": kind, "index": 0, "named": "Hakuno", "skill": skill, "needs": needs}
        expected = ([1] if kind == "add" else []) + [["Hakuno", skill, needs]]
        assert _run("edit", value=[1], edit=edit)["result"] == expected


@pytest.mark.parametrize("edit", [
    {"type": "add", "skill": 1, "needs": []},
    {"type": "add", "needs": []},
    {"type": "add", "named": "Hakuno", "skill": 3, "needs": [], "option": "R"},
    {"type": "add", "named": "Kukulkan", "skill": 1, "needs": [], "option": 0},
    {"type": "add", "named": "Soujyuro", "skill": 3, "needs": [], "option": "Q"},
    {"type": "add", "named": "Hakuno", "skill": 1, "needs": [], "target": 1},
    {"type": "add", "named": "Hakuno", "skill": 1, "needs": [], "swap": [1, 4]},
    {"type": "add", "named": "Hakuno", "skill": 1, "needs": [], "choice": 1},
    {"type": "add", "named": "Hakuno", "skill": 3, "needs": []},
    {"type": "add", "named": "Hakuno", "needs": []},
    {"type": "add", "named": "Hakuno", "skill": 1, "needs": None},
])
def test_hakuno_needs_edits_cannot_silently_drop_parameters_or_become_other_skill_domains(edit):
    assert _run("edit", value=[1], edit=edit)["error"]


def test_hakuno_needs_source_edits_replace_only_the_selected_skill_value():
    prefix = '{"metadata":{"float":1.0,"large":9007199254740993},"round1_turn0_skill":'
    suffix = ',"round1_turn0_np":[2],"round2_extraSkill":[1.0]}'
    needs = [["1B", "1B"], ["S0", "2AS9007199254740993"]]
    result = _source("edit", prefix + '[1]' + suffix,
                     edit={"type": "add", "named": "Hakuno", "skill": 4, "needs": needs})
    assert result["error"] is None
    command = json.dumps(["Hakuno", 4, needs], separators=(",", ":"))
    assert result["result"] == prefix + '[1,' + command + ']' + suffix


@pytest.mark.parametrize("command", ['["Hakuno",1.0,[]]', '["Hakuno",4e0,[["1B"]]]', '["Hakuno",7.0,[["S0"]]]',
                                     '["Hakuno",1,[[1.0]]]', '["Hakuno",1,[["S01"]]]'])
def test_float_skill_tokens_and_non_original_card_needs_remain_read_only(command):
    source = '{"round1_turn0_skill":[' + command + '],"metadata":1.0}'
    assert _source("inspect", source)["result"]["commands"] is None
    assert _source("edit", source, edit={"type": "add"})["error"]
    cleared = _source("edit", source, edit={"type": "clear"})
    assert json.loads(cleared["result"])["round1_turn0_skill"] == []
    assert type(json.loads(cleared["result"])["metadata"]) is float
