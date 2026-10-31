import json
from pathlib import Path
import shutil
import subprocess

import pytest

NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="Node.js is not installed.")
MODULE = Path(__file__).resolve().parents[1] / "webapp" / "static" / "assist-equips-source.js"


def _run(action, source="{}", **payload):
    script = f"""
        import * as equips from {json.dumps(MODULE.as_uri())};
        import {{ readFileSync }} from 'node:fs';
        const input = JSON.parse(readFileSync(0, 'utf8'));
        const before = JSON.stringify(input);
        let result, error = null;
        try {{ result = input.action === 'names' ? equips.readAssistEquipNames(input.value)
            : input.action === 'inspect' ? equips.inspectAssistEquipSource(input.source)
            : equips.editAssistEquipSource(input.source, input.edit);
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


@pytest.mark.parametrize("value,expected", [(None, []), ("", []), ([], []), ("First", ["First"]),
                                           (["First", "First", "Second"], ["First", "Second"]),
                                           ([["First", None, ""], ["Second", "First"], []], ["First", "Second"]),
                                           (["1.0", "9007199254740993"], ["1.0", "9007199254740993"])])
def test_ce_name_inspection_retains_original_nested_order_and_deduplicated_display(value, expected):
    assert _run("names", value=value)["result"] == expected


@pytest.mark.parametrize("edit,expected", [
    ({"type": "add", "name": "Third"}, [["First", None, ""], ["Second", "First"], [], "Third"]),
    ({"type": "remove", "name": "First"}, [[None, ""], ["Second"], []]),
    ({"type": "remove", "name": "Second"}, [["First", None, ""], ["First"], []]),
    ({"type": "clear"}, []),
])
def test_ce_edits_only_replace_the_selected_source_value_and_preserve_group_shape(edit, expected):
    prefix = '{"metadata":{"float":1.0,"large":9007199254740993},"assistEquip":'
    suffix = ',"round1_turn0_skill":[1.0],"custom":2e0}'
    value = [["First", None, ""], ["Second", "First"], []]
    source = prefix + json.dumps(value) + suffix
    result = _run("edit", source, edit=edit)
    assert result["error"] is None
    assert result["result"] == prefix + json.dumps(expected, separators=(",", ":")) + suffix


@pytest.mark.parametrize("value", [None, "", "First", [], ["First"]])
def test_adding_a_ce_retains_legacy_scalar_and_empty_value_behavior(value):
    source = '{"assistEquip":' + json.dumps(value) + ',"metadata":1.0}'
    result = _run("edit", source, edit={"type": "add", "name": "Second"})
    assert result["error"] is None
    expected = ["First", "Second"] if value in ("First", ["First"]) else ["Second"]
    assert json.loads(result["result"])["assistEquip"] == expected
    assert type(json.loads(result["result"])["metadata"]) is float


def test_absent_ce_fields_do_not_appear_until_an_explicit_add():
    source = '{"metadata":{"float":1.0,"large":9007199254740993},"round1_turn0_skill":[1.0]}'
    assert _run("inspect", source)["result"] == {"names": [], "error": None, "canClear": False}
    for edit in ({"type": "clear"}, {"type": "remove", "name": "First"}):
        assert _run("edit", source, edit=edit)["result"] == source
    added = _run("edit", source, edit={"type": "add", "name": "First"})
    saved = json.loads(added["result"])
    assert saved["assistEquip"] == ["First"]
    assert type(saved["metadata"]["float"]) is float
    assert saved["metadata"]["large"] == 9007199254740993
    assert type(saved["round1_turn0_skill"][0]) is float


@pytest.mark.parametrize("edit", [{"type": "add", "name": "First"}, {"type": "remove", "name": "Missing"}])
def test_duplicate_adds_and_missing_removals_are_exact_no_ops(edit):
    source = '{"assistEquip": [ ["First", "First"], null ], "metadata":1.0}'
    assert _run("edit", source, edit=edit)["result"] == source


def test_clearing_an_already_empty_ce_array_is_an_exact_no_op():
    source = '{"assistEquip": [ ], "metadata":1.0}'
    assert _run("inspect", source)["result"] == {"names": [], "error": None, "canClear": False}
    assert _run("edit", source, edit={"type": "clear"})["result"] == source


@pytest.mark.parametrize("value", [0, True, {}, {"name": "First"}, [1.0], [False], [["First"], {"keep": 1.0}]])
def test_unsupported_ce_values_are_read_only_until_explicit_clear(value):
    source = '{"assistEquip":' + json.dumps(value) + ',"metadata":1.0}'
    state = _run("inspect", source)["result"]
    assert state == {"names": None, "error": "Unsupported CE value.", "canClear": True}
    for action in ("add", "remove"):
        assert _run("edit", source, edit={"type": action, "name": "First"})["error"] == "Unsupported CE value."
    assert _run("edit", source, edit={"type": "clear"})["result"] == '{"assistEquip":[],"metadata":1.0}'


def test_decoded_duplicate_ce_keys_block_every_action_including_clear():
    source = '{"assistEquip":["First"],"assistE\\u0071uip":["Second"],"metadata":1.0}'
    assert _run("inspect", source)["error"] == "Ambiguous CE field."
    for edit in ({"type": "clear"}, {"type": "add", "name": "Third"}, {"type": "remove", "name": "First"}):
        assert _run("edit", source, edit=edit)["error"] == "Ambiguous CE field."


def test_single_escaped_ce_keys_and_unrelated_duplicates_remain_intact():
    source = '{"assistE\\u0071uip":["First"],"metadata":1.0,"metadata":2e0}'
    result = _run("edit", source, edit={"type": "add", "name": "Second"})
    assert result["result"] == '{"assistE\\u0071uip":["First","Second"],"metadata":1.0,"metadata":2e0}'


def test_ce_value_bound_counts_nested_nodes_and_checks_a_new_add_without_mutation():
    accepted = ["First"] * 999
    assert _run("names", value=accepted)["result"] == ["First"]
    assert _run("names", value=accepted + ["Second"])["error"] == "CE list exceeds 1,000 values."
    source = '{"assistEquip":' + json.dumps(accepted) + ',"metadata":1.0}'
    assert _run("edit", source, edit={"type": "add", "name": "Second"})["error"] == "CE list exceeds 1,000 values."


@pytest.mark.parametrize("edit", [None, {}, {"type": "unknown"}, {"type": "add"}, {"type": "add", "name": ""},
                                {"type": "remove", "name": None}, {"type": "remove", "name": 1}])
def test_invalid_ce_edits_never_guess_actions_or_coerce_names(edit):
    assert _run("edit", '{}', edit=edit)["error"] == "Invalid CE edit."


@pytest.mark.parametrize("source", ['{', '[]', 'null', '{"assistEquip":[],}', '{/*comment*/"assistEquip":[]}'])
def test_ce_source_inspection_and_edits_require_a_strict_json_object(source):
    assert _run("inspect", source)["error"] == "Invalid script JSON."
    assert _run("edit", source, edit={"type": "clear"})["error"] == "Invalid script JSON."
