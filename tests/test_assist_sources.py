import json
from pathlib import Path
import shutil
import subprocess

import pytest

NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="Node.js is not installed.")
MODULE = Path(__file__).resolve().parents[1] / "webapp" / "static" / "assist-source.js"
MODES = ["\u4ece\u8005\u793c\u88c5", "\u4ec5\u4ece\u8005", "\u4ec5\u793c\u88c5", "\u4e0d\u8bc6\u522b", "\u51a0\u4f4d\u52a9\u6218", "\u51a0\u4f4d\u52a9\u6218\u4ec5\u793c\u88c5"]
VALID = [("assistMode", mode) for mode in MODES] + [("NPlevel", level) for level in range(1, 6)]
VALID += [(field, value) for field in ("onlyFriendAssist", "allNotSkip", "fullEquip", "noGrandRefresh") for value in (False, True)]
VALID += [("jbType", value) for value in ("\u4efb\u610f", "\u521d\u59cb", "NP50")]
VALID += [("servantLevel", value) for value in (1, 120)]
VALID += [("intervalAFswipeAssist", value) for value in (0, 0.75, 10)]
VALID += [("scrollLimit", value) for value in (0, 0.85, 1)]
FIELDS = list(dict.fromkeys(field for field, _value in VALID))


def _run(action, source, **payload):
    script = f"""
        import * as assist from {json.dumps(MODULE.as_uri())};
        import {{ readFileSync }} from 'node:fs';
        const input = JSON.parse(readFileSync(0, 'utf8'));
        const before = JSON.stringify(input);
        let result, error = null;
        try {{ result = input.action === 'inspect' ? assist.inspectAssistSource(input.source)
            : assist.editAssistSource(input.source, input.edit);
        }} catch (failure) {{ error = failure.message; }}
        process.stdout.write(JSON.stringify({{result, error, unchanged: before === JSON.stringify(input)}}));
    """
    response = subprocess.run([NODE, "--input-type=module", "-e", script],
                              input=json.dumps({"action": action, "source": source, **payload}),
                              text=True, capture_output=True, timeout=10, check=False)
    assert response.returncode == 0, response.stderr
    result = json.loads(response.stdout)
    assert result["unchanged"] is True
    return result


@pytest.mark.parametrize("field,value", VALID)
def test_assist_scalar_replacement_changes_only_the_chosen_source_span(field, value):
    prefix = '{"metadata":{"float":1.0,"large":9007199254740993},"' + field + '":'
    suffix = ',"round1_turn0_skill":[1.0],"round1_turn0_np":[2],"custom":2e0}'
    result = _run("edit", prefix + 'null' + suffix, edit={"type": "set", "field": field, "value": value})
    assert result["error"] is None
    assert result["result"] == prefix + json.dumps(value, ensure_ascii=False, separators=(",", ":")) + suffix


@pytest.mark.parametrize("field,value", VALID)
def test_inserting_assist_scalars_preserves_unrelated_numeric_types(field, value):
    source = '{"metadata":{"float":1.0,"large":9007199254740993},"round1_turn0_skill":[1.0],"legacy":2e0}'
    result = _run("edit", source, edit={"type": "set", "field": field, "value": value})
    assert result["error"] is None
    saved = json.loads(result["result"])
    assert saved[field] == value
    assert type(saved["metadata"]["float"]) is float
    assert saved["metadata"]["large"] == 9007199254740993
    assert type(saved["round1_turn0_skill"][0]) is float
    assert json.loads(result["result"], parse_float=str)["legacy"] == "2e0"


@pytest.mark.parametrize("field", FIELDS)
def test_decoded_duplicate_assist_fields_are_reported_and_never_replaced(field):
    escaped = f"\\u{ord(field[0]):04x}" + field[1:]
    source = '{"' + field + '":null,"' + escaped + '":true,"metadata":1.0}'
    state = _run("inspect", source)
    assert state["error"] is None
    assert state["result"] == {"ambiguous": [field]}
    value = next(value for name, value in VALID if name == field)
    assert _run("edit", source, edit={"type": "set", "field": field, "value": value})["error"] == "Ambiguous assist field."


def test_single_escaped_keys_keep_their_original_spelling():
    source = '{"NP\\u006cevel":null,"metadata":1.0}'
    assert _run("inspect", source)["result"] == {"ambiguous": []}
    result = _run("edit", source, edit={"type": "set", "field": "NPlevel", "value": 3})
    assert result["result"] == '{"NP\\u006cevel":3,"metadata":1.0}'


def test_unrelated_duplicate_keys_do_not_block_or_normalize_assist_edits():
    source = '{"metadata":1.0,"metadata":2e0,"NPlevel":1}'
    assert _run("inspect", source)["result"] == {"ambiguous": []}
    assert _run("edit", source, edit={"type": "set", "field": "NPlevel", "value": 2})["result"] == '{"metadata":1.0,"metadata":2e0,"NPlevel":2}'


@pytest.mark.parametrize("field,value", [("assistMode", "Future"), ("assistMode", None), ("assistMode", 1),
                                        ("NPlevel", True), ("NPlevel", "3"), ("NPlevel", 0), ("NPlevel", 6), ("NPlevel", 2.5),
                                        ("servantLevel", 0), ("servantLevel", 121), ("servantLevel", 3.5),
                                        ("onlyFriendAssist", 1), ("allNotSkip", []), ("fullEquip", "true"), ("noGrandRefresh", None),
                                        ("jbType", "Any"), ("jbType", 0), ("intervalAFswipeAssist", -0.1),
                                        ("intervalAFswipeAssist", 10.1), ("intervalAFswipeAssist", "0.5"),
                                        ("scrollLimit", -0.1), ("scrollLimit", 1.1), ("scrollLimit", False)])
def test_assist_source_edits_reject_invalid_values_without_coercion(field, value):
    assert _run("edit", '{}', edit={"type": "set", "field": field, "value": value})["error"] == "Invalid assist edit."


@pytest.mark.parametrize("edit", [None, {}, {"type": "set", "field": "metadata", "value": 1},
                                {"type": "remove", "field": "NPlevel"}, {"type": "set", "field": "NPlevel"},
                                {"type": "set", "field": "__proto__", "value": "CH"}])
def test_assist_source_editor_is_limited_to_explicit_owned_scalar_edits(edit):
    assert _run("edit", '{}', edit=edit)["error"] == "Invalid assist edit."


@pytest.mark.parametrize("source", ['{', '[]', 'null', '1', '{"NPlevel":1,}', '{/*comment*/"NPlevel":1}'])
def test_assist_inspection_and_edits_require_a_strict_json_object(source):
    assert _run("inspect", source)["error"] == "Invalid script JSON."
    assert _run("edit", source, edit={"type": "set", "field": "NPlevel", "value": 2})["error"] == "Invalid script JSON."
