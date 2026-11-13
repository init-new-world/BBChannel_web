import json
from pathlib import Path
import shutil
import subprocess

import pytest


NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="Node.js is not installed.")
MODULE = Path(__file__).resolve().parents[1] / "webapp" / "static" / "turn-conditions-model.js"


def _run(action, **payload):
    script = f"""
        import * as conds from {json.dumps(MODULE.as_uri())};
        import {{ readFileSync }} from 'node:fs';
        const input = JSON.parse(readFileSync(0, 'utf8'));
        const before = JSON.stringify(input.value);
        let result, error = null;
        try {{
            if (input.action === 'field') result = conds.conditionField(input.field);
            else if (input.action === 'decode-np') result = conds.decodeNpCondition(input.value);
            else if (input.action === 'decode-cmd') result = conds.decodeConditionCommand(input.value);
            else if (input.action === 'make-start') result = conds.makeConditionStart(input.edit);
            else if (input.action === 'read') result = conds.readMixedSkillEntries(input.value);
            else if (input.action === 'valid-strat') result = conds.isValidConditionStrategyPayload(input.value);
            else result = conds.changeMixedSkillSequence(input.value, input.edit);
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
    ("round1_turn0_strategy", "round1_turn0_condition"),
    ("round2_turn19_strategy", "round2_turn19_condition"),
    ("round0_extraStrategy", "round0_extraCondition"),
])
def test_condition_field_maps_regular_and_extra_turns(field, expected):
    assert _run("field", field=field) == {"result": expected, "error": None, "unchanged": True}


@pytest.mark.parametrize("field", [None, "", "round01_turn0_strategy", "round1_turn01_strategy", "other"])
def test_condition_field_rejects_invalid_keys(field):
    assert _run("field", field=field)["error"]


def test_decode_and_build_condition_commands():
    start_cmd = ["Start", 1, [1, 0], ["np", [1, "≥", 100], [0, "≤", 200], [1, "≥", 300]]]
    decoded = _run("decode-cmd", value=start_cmd)["result"]
    assert decoded == {
        "kind": "condition-start",
        "mode": 1,
        "checks": [True, False],
        "hasNp": True,
        "npChecks": [
            {"enabled": True, "op": "≥", "value": 100},
            {"enabled": False, "op": "≤", "value": 200},
            {"enabled": True, "op": "≥", "value": 300},
        ],
    }
    assert _run("decode-cmd", value=["End"])["result"] == {"kind": "condition-end"}
    assert _run("make-start", edit={
        "mode": 0,
        "checks": [True, False],
        "npChecks": [
            {"enabled": False, "op": "≥", "value": 100},
            {"enabled": False, "op": "≥", "value": 100},
            {"enabled": False, "op": "≥", "value": 100},
        ],
        "includeNp": False,
    })["result"] == ["Start", 0, [1, 0]]


@pytest.mark.parametrize("bad_edit", [
    {"mode": 2, "checks": []},
    {"mode": 1, "checks": [2]},
    {"mode": 1, "checks": [], "npChecks": [{"enabled": True, "op": "≥", "value": 100}]},
    {"mode": 1, "checks": [], "npChecks": [{"enabled": True, "op": "=", "value": 100}, {"enabled": False, "op": "≥", "value": 100}, {"enabled": False, "op": "≥", "value": 100}]},
    {"mode": 1, "checks": [], "npChecks": [{"enabled": True, "op": "≥", "value": 301}, {"enabled": False, "op": "≥", "value": 100}, {"enabled": False, "op": "≥", "value": 100}]},
])
def test_make_condition_start_rejects_invalid_inputs(bad_edit):
    assert _run("make-start", edit=bad_edit)["error"]


def test_mixed_skill_sequence_edits_basic_and_condition_blocks():
    seq = [1, ["Start", 1, [1]], [5, 2], ["End"]]
    assert _run("read", value=seq)["result"] == seq

    updated = _run("edit", value=seq, edit={
        "type": "update-condition-start",
        "index": 1,
        "mode": 0,
        "checks": [0, 1],
        "npChecks": [
            {"enabled": True, "op": "≤", "value": 50},
            {"enabled": False, "op": "≥", "value": 100},
            {"enabled": False, "op": "≥", "value": 100},
        ],
        "includeNp": True,
    })
    assert updated["error"] is None
    assert updated["result"][1] == ["Start", 0, [0, 1], ["np", [1, "≤", 50], [0, "≥", 100], [0, "≥", 100]]]

    with_end = _run("edit", value=[1], edit={"type": "add-condition-end"})["result"]
    assert with_end == [1, ["End"]]

    moved = _run("edit", value=with_end, edit={"type": "move", "index": 1, "to": 0})["result"]
    assert moved == [["End"], 1]

    assert _run("valid-strat", value={
        "card1": {"type": 0, "cards": [1], "criticalStar": 0, "more_or_less": True},
        "card2": {"type": 1, "cards": ["Red"], "criticalStar": 0, "more_or_less": True},
        "card3": {"type": 2, "cards": [1], "criticalStar": 0, "more_or_less": True},
        "breakpoint": [0, 0, 0],
        "colorFirst": False,
    })["result"] is True
    assert _run("valid-strat", value={"card1": {}})["result"] is False
