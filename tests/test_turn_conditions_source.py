import json
from pathlib import Path
import shutil
import subprocess

import pytest


NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="Node.js is not installed.")
MODULE = Path(__file__).resolve().parents[1] / "webapp" / "static" / "turn-conditions-source.js"


def _run(action, source, field="round1_turn0_strategy", edit=None):
    script = f"""
        import * as conds from {json.dumps(MODULE.as_uri())};
        import {{ readFileSync }} from 'node:fs';
        const input = JSON.parse(readFileSync(0, 'utf8'));
        try {{
            let result;
            if (input.action === 'inspect-skill') result = conds.inspectMixedSkillSource(input.source, input.field);
            else if (input.action === 'edit-skill') result = conds.changeMixedSkillSource(input.source, input.field, input.edit);
            else if (input.action === 'inspect-cond') result = conds.inspectConditionSource(input.source, input.field);
            else result = conds.changeConditionSource(input.source, input.field, input.edit);
            process.stdout.write(JSON.stringify({{ result, error: null }}));
        }} catch (error) {{ process.stdout.write(JSON.stringify({{ error: error.message }})); }}
    """
    response = subprocess.run([NODE, "--input-type=module", "-e", script],
                              input=json.dumps({"action": action, "source": source, "field": field, "edit": edit}),
                              text=True, capture_output=True, timeout=10, check=False)
    assert response.returncode == 0, response.stderr
    return json.loads(response.stdout)


def _preset():
    entry = {
        "card1": {"type": 0, "cards": [1], "criticalStar": 0, "more_or_less": True},
        "card2": {"type": 1, "cards": ["Red"], "criticalStar": 0, "more_or_less": True},
        "card3": {"type": 2, "cards": [1], "criticalStar": 0, "more_or_less": True},
        "breakpoint": [0, 0, 0],
        "colorFirst": False,
    }
    return {
        "validation": {"ok": True},
        "entries": [{"strategy": entry}],
        "source": json.dumps([{"strategy": entry}], separators=(",", ":")),
    }


def test_mixed_skill_source_preserves_unrelated_floats_and_large_ints():
    source = '{"metadata":{"float":1.0,"large":9007199254740993},"round1_turn0_skill":[1]}'
    res = _run("edit-skill", source, edit={"type": "add-condition-start", "mode": 1, "checks": [0]})
    assert res["error"] is None
    parsed = json.loads(res["result"])
    assert type(parsed["metadata"]["float"]) is float
    assert parsed["metadata"]["large"] == 9007199254740993
    assert parsed["round1_turn0_skill"] == [1, ["Start", 1, [0]]]

    res2 = _run("edit-skill", res["result"], edit={"type": "add-condition-end"})
    assert json.loads(res2["result"])["round1_turn0_skill"] == [1, ["Start", 1, [0]], ["End"]]


def test_mixed_skill_source_rejects_float_tokens_inside_condition_blocks():
    source = '{"round1_turn0_skill":[["Start",1.0,[0]]]}'
    state = _run("inspect-skill", source)["result"]
    assert state["commands"] is None
    assert state["error"]
    assert state["canClear"] is True


def test_condition_source_append_move_remove_and_clear():
    source = '{"metadata":{"float":1.0,"large":9007199254740993},"round1_turns":1}'
    inspected = _run("inspect-cond", source)["result"]
    assert inspected == {"field": "round1_turn0_condition", "entries": [], "error": None, "canClear": False}

    added1 = _run("edit-cond", source, edit={"type": "append-preset", "preset": _preset()})
    assert added1["error"] is None
    parsed_added1 = json.loads(added1["result"])
    assert type(parsed_added1["metadata"]["float"]) is float
    assert parsed_added1["metadata"]["large"] == 9007199254740993
    assert len(parsed_added1["round1_turn0_condition"]) == 1

    preset2 = _preset()
    preset2["entries"][0]["strategy"]["colorFirst"] = True
    preset2["source"] = json.dumps([{"strategy": preset2["entries"][0]["strategy"]}], separators=(",", ":"))
    added2 = _run("edit-cond", added1["result"], edit={"type": "append-preset", "preset": preset2})
    assert len(json.loads(added2["result"])["round1_turn0_condition"]) == 2

    moved = _run("edit-cond", added2["result"], edit={"type": "move", "index": 1, "to": 0})
    parsed_moved = json.loads(moved["result"])
    assert [e["colorFirst"] for e in parsed_moved["round1_turn0_condition"]] == [True, False]

    removed1 = _run("edit-cond", moved["result"], edit={"type": "remove", "index": 0})
    assert len(json.loads(removed1["result"])["round1_turn0_condition"]) == 1

    removed_last = _run("edit-cond", removed1["result"], edit={"type": "remove", "index": 0})
    assert "round1_turn0_condition" not in json.loads(removed_last["result"])


def test_extra_condition_field_mapping_and_invalid_condition_payload():
    source = '{"round2_extraCondition":[{"bad":1}]}'
    inspected = _run("inspect-cond", source, field="round2_extraStrategy")["result"]
    assert inspected["field"] == "round2_extraCondition"
    assert inspected["entries"] is None
    assert inspected["error"]
    assert inspected["canClear"] is True
    cleared = _run("edit-cond", source, field="round2_extraStrategy", edit={"type": "clear"})
    assert "round2_extraCondition" not in json.loads(cleared["result"])
