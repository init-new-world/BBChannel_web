import json
from pathlib import Path
import shutil
import subprocess

import pytest

NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="Node.js is not installed.")
MODULE = Path(__file__).resolve().parents[1] / "webapp" / "static" / "settlement-source.js"
FLAGS = ("fullFriendshipStop", "addFriend")
FIELDS = (*FLAGS, "ignoreFriendship")
VALID = [(field, value) for field in FLAGS for value in (False, True)]
VALID += [("ignoreFriendship", value) for value in (
    "", "245", "x1,3", " 00,-6;9 ", "[1, 3]", "false", "1.0",
    '"quoted"\\path\n\t', "\u4f4d\u7f6e1",
)]
LEGACY = ["null", "0", "1.0", "2e0", "9007199254740993", '["1",3.0,true]', '{"future":1.0}']


def _run(action, source, **payload):
    script = f"""
        import * as settlement from {json.dumps(MODULE.as_uri())};
        import {{ readFileSync }} from 'node:fs';
        const input = JSON.parse(readFileSync(0, 'utf8'));
        const before = JSON.stringify(input);
        let result, error = null;
        try {{ result = input.action === 'inspect' ? settlement.inspectSettlementSource(input.source)
            : settlement.editSettlementSource(input.source, input.edit);
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
def test_settlement_replacement_changes_only_the_chosen_source_span(field, value):
    prefix = '{"metadata":{"float":1.0,"large":9007199254740993},"' + field + '":'
    suffix = ',"round1_turn0_skill":[1.0,[1,2.0]],"round1_turn0_np":[2],"custom":2e0,"custom":-0.0}'
    result = _run("edit", prefix + "null" + suffix, edit={"type": "set", "field": field, "value": value})
    assert result["error"] is None
    assert result["result"] == prefix + json.dumps(value, ensure_ascii=False, separators=(",", ":")) + suffix


@pytest.mark.parametrize("field,value", VALID)
def test_settlement_insertion_preserves_numeric_lexemes_and_unrelated_duplicate_pairs(field, value):
    source = ('{"metadata":{"float":1.0,"large":9007199254740993},'
              '"round1_turn0_skill":[1.0,[1,2.0]],"round1_turn0_np":[2],'
              '"legacy":2e0,"negativeZero":-0,"tiny":1e-999,"huge":1e999,"custom":2E+0,"custom":-0.0}')
    result = _run("edit", source, edit={"type": "set", "field": field, "value": value})
    assert result["error"] is None
    saved = json.loads(result["result"])
    assert saved[field] == value
    assert type(saved[field]) is type(value)
    assert type(saved["metadata"]["float"]) is float
    assert saved["metadata"]["large"] == 9007199254740993
    assert type(saved["round1_turn0_skill"][0]) is float
    assert type(saved["round1_turn0_skill"][1][1]) is float
    original_pairs = json.loads(source, object_pairs_hook=list, parse_float=str, parse_int=str)
    saved_pairs = json.loads(result["result"], object_pairs_hook=list, parse_float=str, parse_int=str)
    assert sum(name == field for name, _value in saved_pairs) == 1
    assert [(name, item) for name, item in saved_pairs if name != field] == original_pairs


@pytest.mark.parametrize("field,value", [("fullFriendshipStop", True), ("addFriend", False), ("ignoreFriendship", "245")])
@pytest.mark.parametrize("current", LEGACY)
def test_explicit_settlement_edits_can_replace_any_legacy_target_value(field, value, current):
    prefix = '{"' + field + '":'
    suffix = ',"metadata":1.0}'
    source = prefix + current + suffix
    assert _run("inspect", source)["result"] == {"ambiguous": []}
    result = _run("edit", source, edit={"type": "set", "field": field, "value": value})
    assert result["error"] is None
    assert result["result"] == prefix + json.dumps(value, separators=(",", ":")) + suffix


@pytest.mark.parametrize("field,value", [("fullFriendshipStop", False), ("addFriend", True), ("ignoreFriendship", "")])
def test_other_owned_legacy_values_are_not_coerced_or_normalized(field, value):
    values = {"fullFriendshipStop": '{"future":1.0}', "addFriend": '[0,9007199254740993]',
              "ignoreFriendship": '[1.0,"3",true,null]'}
    source = "{" + ",".join(json.dumps(name) + ":" + current for name, current in values.items()) + "}"
    expected = "{" + ",".join(json.dumps(name) + ":" + (json.dumps(value) if name == field else current)
                               for name, current in values.items()) + "}"
    result = _run("edit", source, edit={"type": "set", "field": field, "value": value})
    assert result["error"] is None
    assert result["result"] == expected


@pytest.mark.parametrize("source", ["{}", '{"metadata":1.0}',
                                  '{"fullFriendshipStop":[],"addFriend":{},"ignoreFriendship":null}'])
def test_settlement_inspection_does_not_insert_defaults_or_validate_legacy_types(source):
    state = _run("inspect", source)
    assert state["error"] is None
    assert state["result"] == {"ambiguous": []}


@pytest.mark.parametrize("field", FIELDS)
@pytest.mark.parametrize("escaped_alias", [False, True], ids=["literal", "escaped"])
def test_duplicate_settlement_keys_block_only_the_targeted_owned_field(field, escaped_alias):
    alias = f"\\u{ord(field[0]):04x}" + field[1:] if escaped_alias else field
    prefix = '{"' + field + '":null,"' + alias + '":true,"metadata":1.0,"'
    other = "addFriend" if field == "fullFriendshipStop" else "fullFriendshipStop"
    source = prefix + other + '":null}'
    state = _run("inspect", source)
    assert state["error"] is None
    assert state["result"] == {"ambiguous": [field]}
    value = "245" if field == "ignoreFriendship" else False
    result = _run("edit", source, edit={"type": "set", "field": field, "value": value})
    assert result["error"] == "Ambiguous settlement field."
    other_result = _run("edit", source, edit={"type": "set", "field": other, "value": True})
    assert other_result["error"] is None
    assert other_result["result"] == prefix + other + '":true}'


def test_all_decoded_duplicate_owned_fields_are_reported_once():
    source = ('{"addFriend":false,"ignoreFriendship":"1","fullFriendshipStop":null,'
              '"\\u0061ddFriend":true,"ignoreFriendship":"3","fullFriendshipStop":1,'
              '"addFriend":[],"fullFriendshipStop":{},"metadata":1.0,"metadata":2e0}')
    state = _run("inspect", source)
    assert state["error"] is None
    assert sorted(state["result"]["ambiguous"]) == sorted(FIELDS)


@pytest.mark.parametrize("field,value", [("fullFriendshipStop", True), ("addFriend", False), ("ignoreFriendship", "")])
def test_single_escaped_settlement_keys_retain_their_original_spelling(field, value):
    escaped = f"\\u{ord(field[0]):04x}" + field[1:]
    prefix = '{"' + escaped + '":'
    suffix = ',"metadata":1.0}'
    source = prefix + "null" + suffix
    assert _run("inspect", source)["result"] == {"ambiguous": []}
    result = _run("edit", source, edit={"type": "set", "field": field, "value": value})
    assert result["error"] is None
    assert result["result"] == prefix + json.dumps(value) + suffix


@pytest.mark.parametrize("field,value", [("fullFriendshipStop", True), ("addFriend", False), ("ignoreFriendship", "245")])
def test_unknown_and_nested_duplicate_keys_are_ignored_and_preserved(field, value):
    prefix = ('{"metadata":1.0,"\\u006detadata":2e0,"__proto__":1.0,"__proto__":2e0,'
              '"nested":{"fullFriendshipStop":1.0,"fullFriendshipStop":2e0,'
              '"addFriend":false,"addFriend":true,"ignoreFriendship":"1","ignoreFriendship":"3"},"'
              + field + '":')
    source = prefix + "null}"
    assert _run("inspect", source)["result"] == {"ambiguous": []}
    result = _run("edit", source, edit={"type": "set", "field": field, "value": value})
    assert result["error"] is None
    assert result["result"] == prefix + json.dumps(value) + "}"


INVALID = [(field, value) for field in FLAGS for value in
           (None, 0, 1, 2.5, "", "true", "false", [], {}, [0], {"enabled": False})]
INVALID += [("ignoreFriendship", value) for value in (None, False, True, 0, 1, 1.5, [], ["1", 3], {"value": "13"})]


@pytest.mark.parametrize("field,value", INVALID)
def test_settlement_source_edits_reject_invalid_values_without_coercion(field, value):
    result = _run("edit", '{}', edit={"type": "set", "field": field, "value": value})
    assert result["error"] == "Invalid settlement edit."


@pytest.mark.parametrize("edit", [None, {}, {"type": "set", "field": "metadata", "value": True},
                                {"type": "remove", "field": "ignoreFriendship"},
                                {"type": "clear", "field": "ignoreFriendship"},
                                {"type": "unset", "field": "addFriend"},
                                {"field": "addFriend", "value": True}, {"type": "set", "value": True},
                                {"type": "set", "field": "addFriend"},
                                {"type": "set", "field": "ignoreFriendship"},
                                {"type": "set", "field": None, "value": True},
                                {"type": "set", "field": [], "value": True},
                                *({"type": "set", "field": field, "value": True} for field in
                                  ("__proto__", "constructor", "toString", "hasOwnProperty", "FullFriendshipStop", "addFriend "))])
def test_settlement_source_editor_only_accepts_explicit_owned_set_operations(edit):
    assert _run("edit", '{}', edit=edit)["error"] == "Invalid settlement edit."


@pytest.mark.parametrize("source", ['{', '[]', 'null', '1', 'true', '"text"',
                                  '{"ignoreFriendship":"13",}', '{/*comment*/"addFriend":true}',
                                  '{} trailing', None, {}, [], True, 1])
def test_settlement_inspection_and_edits_require_a_strict_json_object(source):
    assert _run("inspect", source)["error"] == "Invalid script JSON."
    result = _run("edit", source, edit={"type": "set", "field": "addFriend", "value": True})
    assert result["error"] == "Invalid script JSON."
