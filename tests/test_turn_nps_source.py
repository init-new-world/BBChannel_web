import json
from pathlib import Path
import shutil
import subprocess

import pytest

NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="Node.js is not installed.")
MODULE = Path(__file__).resolve().parents[1] / "webapp" / "static" / "turn-nps-source.js"


def _run(action, source, field="round1_turn0_strategy", edit=None):
    script = f"""
        import * as nps from {json.dumps(MODULE.as_uri())};
        import {{ readFileSync }} from 'node:fs';
        const input = JSON.parse(readFileSync(0, 'utf8'));
        try {{
            const result = input.action === 'inspect' ? nps.inspectNpSource(input.source, input.field)
                : nps.changeNpSource(input.source, input.field, input.edit);
            process.stdout.write(JSON.stringify({{ result, error: null }}));
        }} catch (error) {{ process.stdout.write(JSON.stringify({{ error: error.message }})); }}
    """
    response = subprocess.run([NODE, "--input-type=module", "-e", script],
                              input=json.dumps({"action": action, "source": source, "field": field, "edit": edit}),
                              text=True, capture_output=True, timeout=10, check=False)
    assert response.returncode == 0, response.stderr
    return json.loads(response.stdout)


@pytest.mark.parametrize("edit,expected", [
    ({"type": "select", "index": 0, "servant": 3}, [3, 1, 2]),
    ({"type": "select", "index": 1, "servant": 0}, [2, 3]),
    ({"type": "select", "index": 1, "servant": 2}, [1, 2, 3]),
    ({"type": "clear"}, []),
])
def test_np_edits_only_replace_the_selected_value_and_keep_duplicate_swaps(edit, expected):
    prefix = '{"metadata":{"float":1.0,"large":9007199254740993},"round1_turn0_np":'
    suffix = ',"round1_turn0_skill":[1.0],"round2_turn0_np":[3]}'
    source = prefix + '[2,1,3]' + suffix
    result = _run("edit", source, edit=edit)
    assert result["error"] is None
    assert result["result"] == prefix + json.dumps(expected, separators=(",", ":")) + suffix


def test_absent_np_sequence_can_be_created_without_rounding_other_fields():
    source = '{"server":"CH","round1_turns":1,"metadata":{"float":1.0,"large":9007199254740993}}'
    assert _run("inspect", source)["result"] == {"field": "round1_turn0_np", "nps": [], "error": None, "canClear": False}
    result = _run("edit", source, edit={"type": "select", "index": 0, "servant": 2})
    saved = json.loads(result["result"])
    assert saved["round1_turn0_np"] == [2]
    assert type(saved["metadata"]["float"]) is float
    assert saved["metadata"]["large"] == 9007199254740993


@pytest.mark.parametrize("sequence", ["[1.0]", "[1e0]", "[true]", '"legacy"', "null", "[1,1]", "[1,2,3,1]", "[4]"])
def test_malformed_and_float_np_sequences_are_only_explicitly_clearable(sequence):
    source = '{"round1_turn0_np":' + sequence + ',"metadata":1.0}'
    state = _run("inspect", source)["result"]
    assert state == {"field": "round1_turn0_np", "nps": None, "error": "Invalid NP sequence.", "canClear": True}
    assert _run("edit", source, edit={"type": "select", "index": 0, "servant": 2})["error"]
    assert _run("edit", source, edit={"type": "clear"})["result"] == '{"round1_turn0_np":[],"metadata":1.0}'


@pytest.mark.parametrize("field", ["round1_extraStrategy", "round01_turn0_strategy", "round1_turn01_strategy",
                                   "round9007199254740992_turn0_strategy", "round1_turn9007199254740992_strategy", None])
def test_extra_and_noncanonical_np_targets_never_write(field):
    assert _run("inspect", "{}", field)["error"]
    assert _run("edit", "{}", field, {"type": "clear"})["error"]


@pytest.mark.parametrize("source", ["", "{", "[]", "null", '{"round1_turn0_np":[1],}', '{/*comment*/"round1_turn0_np":[]}'])
def test_np_source_requires_a_strict_json_object(source):
    assert _run("inspect", source)["error"]
    assert _run("edit", source, edit={"type": "clear"})["error"]


@pytest.mark.parametrize("source", [
    '{"round1_turn0_np":[1],"round1_turn0_np":[2]}',
    '{"round1_turn0_np":[1],"round1_turn0_\\u006ep":[2]}',
])
def test_duplicate_np_fields_cannot_be_rewritten_even_by_clear(source):
    assert _run("inspect", source)["error"]
    assert _run("edit", source, edit={"type": "clear"})["error"]


def test_escaped_np_field_identity_is_preserved():
    source = '{"round1_turn0_\\u006ep":[1],"metadata":1.0}'
    result = _run("edit", source, edit={"type": "select", "index": 1, "servant": 2})
    assert result["result"] == '{"round1_turn0_\\u006ep":[1,2],"metadata":1.0}'


@pytest.mark.parametrize("before,index,servant,after", [
    ([1, 2], 2, 1, [2, 1]), ([1], 1, 1, [1]), ([], 0, 0, []), ([1, 2, 3], 2, 0, [1, 2]),
])
def test_selecting_an_existing_np_in_an_empty_slot_moves_it_without_holes(before, index, servant, after):
    source = json.dumps({"round1_turn0_np": before})
    result = _run("edit", source, edit={"type": "select", "index": index, "servant": servant})
    assert result["error"] is None
    assert json.loads(result["result"])["round1_turn0_np"] == after


def test_an_empty_object_and_round_zero_can_hold_an_explicit_np_sequence():
    result = _run("edit", "{}", "round0_turn0_strategy", {"type": "select", "index": 0, "servant": 1})
    assert result["error"] is None
    assert json.loads(result["result"]) == {"round0_turn0_np": [1]}


@pytest.mark.parametrize("edit", [
    {"type": "select", "index": -1, "servant": 2}, {"type": "select", "index": True, "servant": 2},
    {"type": "select", "index": 2, "servant": 2}, {"type": "select", "index": 3, "servant": 2},
    {"type": "select", "index": 0, "servant": True}, {"type": "select", "index": 0, "servant": "2"},
    {"type": "select", "index": 0, "servant": 4}, {"type": "other"}, None,
])
def test_invalid_np_edits_never_modify_source(edit):
    assert _run("edit", '{"round1_turn0_np":[1]}', edit=edit)["error"]
