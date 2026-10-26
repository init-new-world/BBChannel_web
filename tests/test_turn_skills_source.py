import json
from pathlib import Path
import shutil
import subprocess

import pytest


NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="Node.js is not installed.")
MODULE = Path(__file__).resolve().parents[1] / "webapp" / "static" / "turn-skills-source.js"


def _run(action, source, field="round1_turn0_strategy", edit=None):
    script = f"""
        import * as skills from {json.dumps(MODULE.as_uri())};
        import {{ readFileSync }} from 'node:fs';
        const input = JSON.parse(readFileSync(0, 'utf8'));
        try {{
            const result = input.action === 'inspect' ? skills.inspectSkillSource(input.source, input.field)
                : skills.changeSkillSource(input.source, input.field, input.edit);
            process.stdout.write(JSON.stringify({{ result, error: null }}));
        }} catch (error) {{ process.stdout.write(JSON.stringify({{ error: error.message }})); }}
    """
    response = subprocess.run([NODE, "--input-type=module", "-e", script],
                              input=json.dumps({"action": action, "source": source, "field": field, "edit": edit}),
                              text=True, capture_output=True, timeout=10, check=False)
    assert response.returncode == 0, response.stderr
    return json.loads(response.stdout)


@pytest.mark.parametrize("sequence", ["[1.0]", "[1e0]", "[[1.0,2]]", "[[1,2.0]]", "[[1,2e0]]"])
def test_integral_float_tokens_remain_read_only_like_the_python_compiler(sequence):
    source = '{"round1_turn0_skill":' + sequence + ',"metadata":{"float":1.0,"large":9007199254740993}}'
    state = _run("inspect", source)["result"]
    assert state["commands"] is None
    assert state["error"]
    assert state["canClear"] is True
    assert _run("edit", source, edit={"type": "add"})["error"]
    cleared = _run("edit", source, edit={"type": "clear"})
    assert cleared["error"] is None
    parsed = json.loads(cleared["result"])
    assert parsed["round1_turn0_skill"] == []
    assert type(parsed["metadata"]["float"]) is float
    assert parsed["metadata"]["large"] == 9007199254740993


@pytest.mark.parametrize("edit,expected", [
    ({"type": "add", "skill": 12, "target": 3}, [1, [5, 2], [12, 3]]),
    ({"type": "update", "index": 0, "skill": 7, "target": 1}, [[7, 1], [5, 2]]),
    ({"type": "move", "index": 1, "to": 0}, [[5, 2], 1]),
    ({"type": "remove", "index": 0}, [[5, 2]]),
    ({"type": "clear"}, []),
])
def test_existing_skill_edits_only_replace_the_selected_value_span(edit, expected):
    prefix = '{\n "metadata":{"float":1.0,"large":9007199254740993,"name":"原文"},\n "round1_turn0_skill": '
    suffix = ',\n "round2_extraSkill": [8], "extension": "round1_turn0_skill"\n}'
    source = prefix + "[1, [5,2]]" + suffix
    response = _run("edit", source, edit=edit)
    assert response["error"] is None
    assert response["result"].startswith(prefix)
    assert response["result"].endswith(suffix)
    assert json.loads(response["result"])["round1_turn0_skill"] == expected


@pytest.mark.parametrize("field,skill_field", [("round1_turn0_strategy", "round1_turn0_skill"), ("round2_extraStrategy", "round2_extraSkill")])
def test_missing_skill_fields_can_be_added_without_rounding_other_fields(field, skill_field):
    source = '{"metadata":{"float":1.0,"large":9007199254740993},"round2_turns":1}'
    state = _run("inspect", source, field)["result"]
    assert state == {"field": skill_field, "commands": [], "error": None, "canClear": False}
    response = _run("edit", source, field, {"type": "add", "skill": 3, "target": 2})
    parsed = json.loads(response["result"])
    assert parsed[skill_field] == [[3, 2]]
    assert type(parsed["metadata"]["float"]) is float
    assert parsed["metadata"]["large"] == 9007199254740993


@pytest.mark.parametrize("source", ["", "{", "[]", "null", '{"round1_turn0_skill":[1],}', '{/*comment*/"round1_turn0_skill":[]}'])
def test_skill_source_requires_strict_json_object_before_any_edit(source):
    assert _run("inspect", source)["error"]
    assert _run("edit", source, edit={"type": "clear"})["error"]


@pytest.mark.parametrize("source", [
    '{"round1_turn0_skill":[1],"round1_turn0_skill":[2]}',
    '{"round1_turn0_skill":[1],"round1_turn0_\\u0073kill":[2]}',
])
def test_duplicate_skill_fields_never_edit_only_one_of_multiple_meanings(source):
    assert _run("inspect", source)["error"]
    assert _run("edit", source, edit={"type": "clear"})["error"]


def test_escaped_skill_property_names_are_matched_by_decoded_identity():
    source = '{"round1_turn0_\\u0073kill":[1],"metadata":1.0}'
    assert _run("inspect", source)["result"]["commands"] == [1]
    response = _run("edit", source, edit={"type": "add"})
    assert '"round1_turn0_\\u0073kill"' in response["result"]
    assert json.loads(response["result"])["round1_turn0_skill"] == [1, 1]


def test_too_large_source_sequence_is_not_rendered_but_can_be_explicitly_cleared():
    source = json.dumps({"round1_turn0_skill": [1] * 1001})
    state = _run("inspect", source)["result"]
    assert state["commands"] is None
    assert state["error"] == "Skill sequence exceeds 1,000 entries."
    assert state["canClear"] is True
    assert json.loads(_run("edit", source, edit={"type": "clear"})["result"]) == {"round1_turn0_skill": []}
