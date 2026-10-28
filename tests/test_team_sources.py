import json
from pathlib import Path
import shutil
import subprocess

import pytest

NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="Node.js is not installed.")
MODULE = Path(__file__).resolve().parents[1] / "webapp" / "static" / "team-source.js"


def _run(action, source, **payload):
    script = f"""
        import * as team from {json.dumps(MODULE.as_uri())};
        import {{ readFileSync }} from 'node:fs';
        const input = JSON.parse(readFileSync(0, 'utf8'));
        try {{
            const result = input.action === 'inspect' ? team.inspectTeamSource(input.source)
                : input.action === 'used' ? team.editUsedServantsSource(input.source, input.slot, input.checked)
                : team.editTeamSource(input.source, input.edit);
            process.stdout.write(JSON.stringify({{ result, error: null }}));
        }} catch (error) {{ process.stdout.write(JSON.stringify({{ error: error.message }})); }}
    """
    response = subprocess.run([NODE, "--input-type=module", "-e", script],
                              input=json.dumps({"action": action, "source": source, **payload}),
                              text=True, capture_output=True, timeout=10, check=False)
    assert response.returncode == 0, response.stderr
    return json.loads(response.stdout)


@pytest.mark.parametrize("field,value", [("server", "JP"), ("master_equip", "008"), ("master_equip", 0),
                                        ("master_sex", 0), ("master_sex", 1), ("assistIdx", 0), ("assistIdx", 5),
                                        ("servant_0_name", ""), ("servant_5_name", "Support")])
def test_team_scalar_fields_preserve_other_numeric_source_types(field, value):
    source = '{"metadata":{"float":1.0,"large":9007199254740993},"round1_turn0_skill":[1.0]}'
    result = _run("edit", source, edit={"type": "set", "field": field, "value": value})
    assert result["error"] is None
    saved = json.loads(result["result"])
    assert saved[field] == value
    assert type(saved["metadata"]["float"]) is float
    assert saved["metadata"]["large"] == 9007199254740993
    assert type(saved["round1_turn0_skill"][0]) is float


@pytest.mark.parametrize("field", ["server", "master_equip", "assistIdx"])
def test_team_field_removal_keeps_other_values_and_does_not_add_nulls(field):
    source = '{"server":"CH","metadata":1.0,"master_equip":"008","assistIdx":3}'
    result = _run("edit", source, edit={"type": "remove", "field": field})
    assert result["error"] is None
    saved = json.loads(result["result"])
    expected = json.loads(source)
    del expected[field]
    assert saved == expected
    assert type(saved["metadata"]) is float


def test_removing_an_absent_team_field_is_an_exact_no_op():
    source = '{"metadata":1.0}'
    assert _run("edit", source, edit={"type": "remove", "field": "server"})["result"] == source


@pytest.mark.parametrize("edit", [
    {"type": "set", "field": "metadata", "value": 1}, {"type": "set", "field": "server", "value": "ch"},
    {"type": "set", "field": "master_equip", "value": None}, {"type": "set", "field": "master_sex", "value": True},
    {"type": "set", "field": "assistIdx", "value": "3"}, {"type": "set", "field": "assistIdx", "value": 6},
    {"type": "set", "field": "servant_6_name", "value": "Support"}, {"type": "set", "field": "servant_0_name", "value": None},
    {"type": "remove", "field": "master_sex"}, {"type": "remove", "field": "servant_0_name"}, None,
])
def test_invalid_team_edits_do_not_guess_or_coerce_values(edit):
    assert _run("edit", '{}', edit=edit)["error"]


def test_used_servant_inspection_matches_python_integer_tokens_and_defaults():
    assert _run("inspect", '{}')["result"] == {"ambiguous": [], "used": {"valid": True, "slots": [0, 1, 2], "unrecognized": False}}
    source = '{"usedServant":[0.0,1,true,"2",9,{"keep":1.0},9007199254740993,-0]}'
    assert _run("inspect", source)["result"]["used"] == {"valid": True, "slots": [1, 0], "unrecognized": True}


@pytest.mark.parametrize("slot,checked,expected", [(0, True, [1, 2, 0]), (1, False, [0, 2]), (4, True, [0, 1, 2, 4])])
def test_first_verification_edit_uses_default_frontline_slots(slot, checked, expected):
    result = _run("used", '{"metadata":1.0}', slot=slot, checked=checked)
    assert result["error"] is None
    saved = json.loads(result["result"])
    assert saved["usedServant"] == expected
    assert type(saved["metadata"]) is float


@pytest.mark.parametrize("slot,checked", [(0, True), (1, False), (5, True)])
def test_verification_edits_retain_unrecognized_values_and_their_source_types(slot, checked):
    source = '{"usedServant":[0.0,1.0,1,true,"2",9,{"keep":1.0},9007199254740993],"metadata":2.0}'
    result = _run("used", source, slot=slot, checked=checked)
    assert result["error"] is None
    saved = json.loads(result["result"])
    expected = [0.0, 1.0, True, "2", 9, {"keep": 1.0}, 9007199254740993]
    if slot != 1:
        expected.insert(2, 1)
    if checked:
        expected.append(slot)
    assert saved["usedServant"] == expected
    assert type(saved["usedServant"][0]) is float
    assert type(saved["usedServant"][1]) is float
    assert type(saved["usedServant"][5 if slot == 1 else 6]["keep"]) is float
    assert type(saved["metadata"]) is float


@pytest.mark.parametrize("source", ['{"usedServant":null}', '{"usedServant":false}', '{"usedServant":"legacy"}'])
def test_non_array_verification_values_remain_read_only(source):
    assert _run("inspect", source)["result"]["used"]["valid"] is False
    assert _run("used", source, slot=0, checked=True)["error"]


@pytest.mark.parametrize("slot,checked", [(True, True), (6, True), (-1, False), (1, 1), (1, "true")])
def test_invalid_verification_edits_are_rejected(slot, checked):
    assert _run("used", '{}', slot=slot, checked=checked)["error"]


def test_decoded_duplicate_team_fields_are_reported_and_never_edited():
    source = '{"server":"CH","ser\\u0076er":"JP","usedServant":[],"usedServant":[1]}'
    state = _run("inspect", source)["result"]
    assert state["ambiguous"] == ["server", "usedServant"]
    assert state["used"]["valid"] is False
    assert _run("edit", source, edit={"type": "set", "field": "server", "value": "JP"})["error"]
    assert _run("edit", source, edit={"type": "remove", "field": "server"})["error"]
    assert _run("used", source, slot=0, checked=True)["error"]


def test_single_escaped_team_keys_keep_their_spelling_and_can_be_removed_by_identity():
    source = '{"ser\\u0076er":"CH","metadata":1.0}'
    changed = _run("edit", source, edit={"type": "set", "field": "server", "value": "JP"})
    assert changed["result"] == '{"ser\\u0076er":"JP","metadata":1.0}'
    removed = _run("edit", source, edit={"type": "remove", "field": "server"})
    assert removed["error"] is None
    assert json.loads(removed["result"]) == {"metadata": 1.0}
    assert type(json.loads(removed["result"])["metadata"]) is float
