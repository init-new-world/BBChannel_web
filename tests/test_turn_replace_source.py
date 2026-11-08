import json
from pathlib import Path
import shutil
import subprocess

import pytest

NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="Node.js is not installed.")
MODULE = Path(__file__).resolve().parents[1] / "webapp" / "static" / "turn-replace-source.js"


def _run(action, source, field="round1_turn0_strategy", edit=None):
    script = f"""
        import * as replaceMod from {json.dumps(MODULE.as_uri())};
        import {{ readFileSync }} from 'node:fs';
        const input = JSON.parse(readFileSync(0, 'utf8'));
        try {{
            const result = input.action === 'inspect' ? replaceMod.inspectReplaceSource(input.source, input.field)
                : replaceMod.changeReplaceSource(input.source, input.field, input.edit);
            process.stdout.write(JSON.stringify({{ result, error: null }}));
        }} catch (error) {{ process.stdout.write(JSON.stringify({{ error: error.message }})); }}
    """
    response = subprocess.run(
        [NODE, "--input-type=module", "-e", script],
        input=json.dumps({"action": action, "source": source, "field": field, "edit": edit}),
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert response.returncode == 0, response.stderr
    return json.loads(response.stdout)


@pytest.mark.parametrize(
    "edit,expected",
    [
        ({"type": "set", "slot": "1", "sourceSlot": 5}, {"1": 5, "4": None}),
        ({"type": "set", "slot": "4", "sourceSlot": ""}, {"1": 4}),
        ({"type": "set", "slot": "5", "sourceSlot": None}, {"1": 4, "4": None, "5": None}),
        ({"type": "replace", "replacements": {"4": 5, "1": 4, "5": None}}, {"1": 4, "4": 5, "5": None}),
        ({"type": "clear"}, {}),
    ],
)
def test_replace_edits_only_replace_the_selected_value(edit, expected):
    prefix = '{"metadata":{"float":1.0,"large":9007199254740993},"round1_turn0_replace":'
    suffix = ',"round1_turn0_skill":[1.0]}'
    source = prefix + '{"4":null,"1":4}' + suffix
    result = _run("edit", source, edit=edit)
    assert result["error"] is None
    assert result["result"] == prefix + json.dumps(expected, separators=(",", ":")) + suffix


def test_absent_replace_mapping_can_be_created_without_rounding_other_fields():
    source = '{"server":"CH","round1_turns":1,"metadata":{"float":1.0,"large":9007199254740993}}'
    assert _run("inspect", source)["result"] == {
        "field": "round1_turn0_replace",
        "replacements": {},
        "error": None,
        "canClear": False,
    }
    result = _run("edit", source, edit={"type": "set", "slot": 1, "sourceSlot": 4})
    saved = json.loads(result["result"])
    assert saved["round1_turn0_replace"] == {"1": 4}
    assert type(saved["metadata"]["float"]) is float
    assert saved["metadata"]["large"] == 9007199254740993


@pytest.mark.parametrize(
    "mapping",
    [
        '{"1":4.0}',
        '{"1":4e0}',
        '{"1":true}',
        '{"0":4}',
        '{"7":4}',
        '{"1":0}',
        '{"1":7}',
        '{"1":4,"1":5}',
        "[]",
        "null",
    ],
)
def test_malformed_replace_mappings_are_only_explicitly_clearable(mapping):
    source = '{"round1_turn0_replace":' + mapping + ',"metadata":1.0}'
    state = _run("inspect", source)["result"]
    assert state == {
        "field": "round1_turn0_replace",
        "replacements": None,
        "error": "Invalid replacement mapping.",
        "canClear": True,
    }
    assert _run("edit", source, edit={"type": "set", "slot": 1, "sourceSlot": 4})["error"]
    assert _run("edit", source, edit={"type": "clear"})["result"] == '{"round1_turn0_replace":{},"metadata":1.0}'
