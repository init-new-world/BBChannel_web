import json

import pytest

from tests.test_turn_skills_model import NODE, _run
from tests.test_turn_skills_source import _run as _source

pytestmark = pytest.mark.skipif(NODE is None, reason="Node.js is not installed.")

NP_SPELL = "\u4ee4\u5492\u00b7\u5b9d\u5177\u89e3\u653e"
HEAL_SPELL = "\u4ee4\u5492\u00b7\u7075\u57fa\u4fee\u590d"


@pytest.mark.parametrize("spell", [NP_SPELL, HEAL_SPELL])
@pytest.mark.parametrize("target", [1, 2, 3])
def test_original_command_spell_pairs_decode_without_coercion(spell, target):
    assert _run("decode", value=[spell, target])["result"] == {"skill": spell, "target": target}
    commands = [1, [spell, target], [13, 6], [12, 1, 4]]
    assert _run("read", value=commands)["result"] == commands


@pytest.mark.parametrize("value", [NP_SPELL, [NP_SPELL], [HEAL_SPELL, None], [NP_SPELL, True], [NP_SPELL, 0],
                                   [HEAL_SPELL, 4], [HEAL_SPELL, "1"], ["future spell", 1], [NP_SPELL, 1, 4]])
def test_malformed_or_unknown_command_spells_stay_read_only(value):
    assert _run("decode", value=value)["result"] is None
    assert _run("read", value=[value])["error"]
    assert _run("edit", value=[value], edit={"type": "clear"})["result"] == []


@pytest.mark.parametrize("spell", [NP_SPELL, HEAL_SPELL])
def test_command_spell_add_and_update_preserve_other_command_types(spell):
    before = [1, [13, 6], [12, 1, 4]]
    assert _run("edit", value=before, edit={"type": "add", "skill": spell, "target": 3})["result"] == [*before, [spell, 3]]
    assert _run("edit", value=before, edit={"type": "update", "index": 1, "skill": spell, "target": 2})["result"] == [1, [spell, 2], [12, 1, 4]]


@pytest.mark.parametrize("edit", [
    {"type": "add", "skill": NP_SPELL}, {"type": "add", "skill": HEAL_SPELL, "target": None},
    {"type": "add", "skill": NP_SPELL, "target": True}, {"type": "add", "skill": HEAL_SPELL, "target": 4},
    {"type": "add", "skill": NP_SPELL, "target": 2, "swap": [1, 4]},
])
def test_command_spells_require_a_servant_target_and_never_accept_exchange_parameters(edit):
    assert _run("edit", value=[1], edit=edit)["error"]


@pytest.mark.parametrize("spell", [NP_SPELL, HEAL_SPELL])
def test_command_spell_source_edits_preserve_unrelated_numbers(spell):
    prefix = '{"metadata":{"float":1.0,"large":9007199254740993},"round1_turn0_skill":'
    suffix = ',"round1_turn0_np":[2]}'
    source = prefix + '[1]' + suffix
    result = _source("edit", source, edit={"type": "add", "skill": spell, "target": 3})
    assert result["error"] is None
    assert result["result"].startswith(prefix)
    assert result["result"].endswith(suffix)
    assert json.loads(result["result"])["round1_turn0_skill"] == [1, [spell, 3]]


@pytest.mark.parametrize("target", ["1.0", "2e0"])
def test_command_spell_float_targets_remain_read_only(target):
    source = '{"round1_turn0_skill": [[' + json.dumps(NP_SPELL) + ',' + target + ']]}'
    assert _source("inspect", source)["result"]["commands"] is None
    assert _source("edit", source, edit={"type": "add"})["error"]
    assert json.loads(_source("edit", source, edit={"type": "clear"})["result"])["round1_turn0_skill"] == []
