import json
from pathlib import Path
import shutil
import subprocess

import pytest


NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="Node.js is not installed.")
MODULE = Path(__file__).resolve().parents[1] / "webapp" / "static" / "turn-skills-model.js"


def _run(action, **payload):
    script = f"""
        import * as skills from {json.dumps(MODULE.as_uri())};
        import {{ readFileSync }} from 'node:fs';
        const input = JSON.parse(readFileSync(0, 'utf8'));
        const before = JSON.stringify(input.value);
        let result, error = null;
        try {{
            if (input.action === 'field') result = skills.skillField(input.field);
            else if (input.action === 'decode') result = skills.decodeBasicSkill(input.value);
            else if (input.action === 'read') result = skills.readBasicSkills(input.value);
            else result = skills.changeSkillSequence(input.value, input.edit);
        }} catch (failure) {{ error = failure.message; }}
        process.stdout.write(JSON.stringify({{ result, error, unchanged: before === JSON.stringify(input.value) }}));
    """
    output = subprocess.run([NODE, "--input-type=module", "-e", script], input=json.dumps({"action": action, **payload}),
                            text=True, capture_output=True, timeout=10, check=False)
    assert output.returncode == 0, output.stderr
    result = json.loads(output.stdout)
    assert result["unchanged"] is True
    return result


@pytest.mark.parametrize("field,expected", [
    ("round1_turn0_strategy", "round1_turn0_skill"),
    ("round2_turn19_strategy", "round2_turn19_skill"),
    ("round0_extraStrategy", "round0_extraSkill"),
])
def test_skill_field_maps_regular_and_extra_turns(field, expected):
    assert _run("field", field=field) == {"result": expected, "error": None, "unchanged": True}


@pytest.mark.parametrize("field", [None, "", "round01_turn0_strategy", "round1_turn01_strategy", "round1_turn-1_strategy",
                                   "round9007199254740992_turn0_strategy", "round1_turn9007199254740992_strategy", "other"])
def test_skill_field_rejects_noncanonical_or_unsafe_turn_keys(field):
    assert _run("field", field=field)["error"]


@pytest.mark.parametrize("value,expected", [
    (1, {"skill": 1, "target": None}), (12, {"skill": 12, "target": None}),
    ([5, 2], {"skill": 5, "target": 2}), ([10, 3], {"skill": 10, "target": 3}),
    ([1, None], {"skill": 1, "target": None}),
    ([13, 1], {"skill": 13, "target": 1}), ([13, 6], {"skill": 13, "target": 6}),
])
def test_basic_skill_decoder_follows_compiler_number_and_target_rules(value, expected):
    assert _run("decode", value=value)["result"] == expected


@pytest.mark.parametrize("value", [True, "1", 1.5, -1, 0, 13, {}, [1], [1, False], [1, 4], [1, 1, 2],
                                   [13, None], [13, 0], [13, 7], [13, True], ["Start", 1, []], ["Hakuno", 2, []]])
def test_basic_skill_decoder_never_coerces_advanced_or_malformed_commands(value):
    assert _run("decode", value=value)["result"] is None


def test_absent_skill_sequence_can_be_edited_without_manufacturing_commands_on_read():
    assert _run("read")["result"] == []
    assert _run("edit", edit={"type": "add"})["result"] == [1]


def test_reading_basic_sequences_preserves_existing_command_representations():
    value = [1, [5, 2], [12, None], [13, 6]]
    assert _run("read", value=value)["result"] == value


@pytest.mark.parametrize("value", [None, "1", False, {"future": 1}, [1, [13, 0]], [1, ["Start", 1, []], 2, "End"]])
def test_legacy_or_advanced_sequences_are_read_only_until_explicit_clear(value):
    assert _run("read", value=value)["error"]
    assert _run("edit", value=value, edit={"type": "add"})["error"]
    assert _run("edit", value=value, edit={"type": "clear"})["result"] == []


@pytest.mark.parametrize("edit,expected", [
    ({"type": "add", "skill": 12, "target": 3}, [1, [5, 2], [12, 3]]),
    ({"type": "update", "index": 0, "skill": 7, "target": 1}, [[7, 1], [5, 2]]),
    ({"type": "update", "index": 1, "skill": 5, "target": None}, [1, 5]),
    ({"type": "move", "index": 0, "to": 1}, [[5, 2], 1]),
    ({"type": "remove", "index": 1}, [1]),
    ({"type": "clear"}, []),
    ({"type": "add", "skill": 13, "target": 6}, [1, [5, 2], [13, 6]]),
    ({"type": "update", "index": 0, "skill": 13, "target": 1}, [[13, 1], [5, 2]]),
])
def test_basic_skill_edits_preserve_order_and_do_not_mutate_source(edit, expected):
    assert _run("edit", value=[1, [5, 2]], edit=edit)["result"] == expected


@pytest.mark.parametrize("edit", [
    {"type": "update", "index": -1, "skill": 1}, {"type": "remove", "index": 2},
    {"type": "remove", "index": False}, {"type": "move", "index": 0, "to": 2},
    {"type": "move", "index": 0, "to": 0.5}, {"type": "add", "skill": False},
    {"type": "add", "skill": 13}, {"type": "add", "skill": 1, "target": 4},
    {"type": "add", "skill": 1, "target": False}, {"type": "unknown"},
    {"type": "add", "skill": 13, "target": None}, {"type": "add", "skill": 13, "target": 7},
])
def test_invalid_edits_never_modify_the_existing_skill_sequence(edit):
    assert _run("edit", value=[1, [5, 2]], edit=edit)["error"]


def test_skill_sequence_bound_is_checked_before_rendering_or_appending():
    assert _run("read", value=[1] * 1001)["error"]
    assert _run("edit", value=[1] * 1000, edit={"type": "add"})["error"]
    assert len(_run("edit", value=[1] * 1000, edit={"type": "remove", "index": 999})["result"]) == 999
