import json

import pytest

from tests.test_command_spell_model import NP_SPELL
from tests.test_turn_skills_model import NODE, _run
from tests.test_turn_skills_source import _run as _source

pytestmark = pytest.mark.skipif(NODE is None, reason="Node.js is not installed.")


def test_mixed_special_skill_sequences_keep_all_other_command_types_and_order():
    commands = [1, [-2, 3], [13, 6], [NP_SPELL, 2], [12, 1, 4]]
    assert _run("read", value=commands)["result"] == commands
    assert _run("edit", value=commands, edit={"type": "move", "index": 1, "to": 4})["result"] == [1, [13, 6], [NP_SPELL, 2], [12, 1, 4], [-2, 3]]


@pytest.mark.parametrize("edit,expected", [
    ({"type": "add", "skill": -2, "choice": 3}, [1, [-2, 3]]),
    ({"type": "update", "index": 0, "skill": -3, "choice": 2}, [[-3, 2]]),
])
def test_special_skill_edits_use_a_choice_instead_of_a_servant_target(edit, expected):
    assert _run("edit", value=[1], edit=edit)["result"] == expected


@pytest.mark.parametrize("edit", [
    {"type": "add", "skill": -2}, {"type": "add", "skill": -2, "choice": True},
    {"type": "add", "skill": -2, "choice": 1, "target": 2},
    {"type": "add", "skill": -2, "choice": 1, "swap": [1, 4]},
    {"type": "add", "skill": 1, "choice": 2}, {"type": "add", "skill": NP_SPELL, "choice": 2, "target": 1},
])
def test_invalid_special_skill_edits_never_silently_change_command_domain(edit):
    assert _run("edit", value=[1], edit=edit)["error"]


def test_special_skill_source_edits_do_not_canonicalize_unrelated_numbers():
    prefix = '{"metadata":{"float":1.0,"large":9007199254740993},"round1_turn0_skill":'
    suffix = ',"round1_turn0_np":[2]}'
    result = _source("edit", prefix + '[1]' + suffix, edit={"type": "add", "skill": -2, "choice": 3})
    assert result["error"] is None
    assert result["result"] == prefix + '[1,[-2,3]]' + suffix


@pytest.mark.parametrize("command", ['[-2.0,1]', '[-2,1.0]', '[-3,2e0]'])
def test_special_skill_float_tokens_are_not_enabled_by_javascript_parsing(command):
    source = '{"round1_turn0_skill":[' + command + '],"metadata":1.0}'
    assert _source("inspect", source)["result"]["commands"] is None
    assert _source("edit", source, edit={"type": "add"})["error"]
    result = _source("edit", source, edit={"type": "clear"})
    assert json.loads(result["result"])["round1_turn0_skill"] == []
    assert type(json.loads(result["result"])["metadata"]) is float
