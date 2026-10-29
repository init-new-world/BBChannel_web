import json
from pathlib import Path
import shutil
import subprocess

import pytest

NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="Node.js is not installed.")
MODULE = Path(__file__).resolve().parents[1] / "webapp" / "static" / "hakuno-needs-model.js"


def _run(action, **payload):
    script = f"""
        import * as hakuno from {json.dumps(MODULE.as_uri())};
        import {{ readFileSync }} from 'node:fs';
        const input = JSON.parse(readFileSync(0, 'utf8'));
        const before = JSON.stringify(input);
        let result, error = null;
        try {{
            if (input.action === 'decode') result = hakuno.decodeHakunoNeeds(input.command);
            else if (input.action === 'read') result = hakuno.readHakunoNeeds(input.needs);
            else if (input.action === 'card') result = hakuno.isHakunoCardCode(input.code);
            else if (input.action === 'edit') result = hakuno.changeHakunoNeeds(input.needs, input.edit);
            else if (input.action === 'sparse') {{
                const needs = [input.partial ? ['1B', , '2A'] : Array(1)];
                const rejects = (run) => {{ try {{ run(); return false; }} catch {{ return true; }} }};
                result = {{
                    read: rejects(() => hakuno.readHakunoNeeds(needs)),
                    make: rejects(() => hakuno.makeHakunoNeeds(1, needs)),
                    edit: rejects(() => hakuno.changeHakunoNeeds(needs, {{type:'add'}})),
                    decode: hakuno.decodeHakunoNeeds(['Hakuno', 1, needs]),
                    clear: hakuno.changeHakunoNeeds(needs, {{type:'clear'}}),
                }};
            }}
            else if (input.action === 'isolation') {{
                const decoded = hakuno.decodeHakunoNeeds(input.command);
                const made = hakuno.makeHakunoNeeds(input.command[1], input.command[2]);
                decoded.needs[0].push('2A');
                made[2][0].push('3Q');
                result = true;
            }} else result = hakuno.makeHakunoNeeds(input.skill, input.needs);
        }} catch (failure) {{ error = failure.message; }}
        process.stdout.write(JSON.stringify({{ result, error, unchanged: before === JSON.stringify(input) }}));
    """
    response = subprocess.run([NODE, "--input-type=module", "-e", script],
                              input=json.dumps({"action": action, **payload}), text=True,
                              capture_output=True, timeout=10, check=False)
    assert response.returncode == 0, response.stderr
    result = json.loads(response.stdout)
    assert result["unchanged"] is True
    return result


@pytest.mark.parametrize("skill", [1, 4, 7])
@pytest.mark.parametrize("needs", [[], [[]], [["1B"]], [["1B", "1B", "2A"], ["3Q"]],
                                  [["S0", "2AS10"], ["3BS9007199254740993"]]])
def test_original_hakuno_first_skill_keeps_alternative_groups_repeated_cards_and_opaque_tag_indices(skill, needs):
    command = ["Hakuno", skill, needs]
    assert _run("decode", command=command)["result"] == {"named": "Hakuno", "skill": skill, "needs": needs, "target": None}
    assert _run("make", skill=skill, needs=needs)["result"] == command


@pytest.mark.parametrize("code", [f"{slot}{color}" for slot in (1, 2, 3) for color in "ABQ"] + ["S0", "S1", "S10", "2BS0", "3QS100"])
def test_hakuno_card_codes_match_original_ordinary_and_custom_tag_forms(code):
    assert _run("card", code=code)["result"] is True


@pytest.mark.parametrize("code", [None, 1, True, [], "", "1N", "4B", "0A", "1b", "S", "S01", "S-1", "s0", "1BS01", "1BS0x", " 1B", "2A "])
def test_invalid_card_codes_are_not_normalized_or_coerced(code):
    assert _run("card", code=code)["result"] is False


@pytest.mark.parametrize("command", [None, "Hakuno", [], ["Hakuno"], ["Hakuno", 1], ["Hakuno", 1, [], 2],
                                     ["Hakuno", True, []], ["Hakuno", 0, []], ["Hakuno", 2, []], ["Hakuno", 3, "R"],
                                     ["Hakuno", 5, []], ["Hakuno", 8, []], ["Hakuno", 10, []], ["Hakuno", "1", []],
                                     ["Hakuno", 1, None], ["Hakuno", 1, ["1B"]], ["Hakuno", 1, [[1]]],
                                     ["Hakuno", 1, [["1B"] * 6]], ["Future", 1, []], ["hakuno", 1, []]])
def test_non_original_hakuno_commands_remain_unrecognized(command):
    assert _run("decode", command=command)["result"] is None


def test_hakuno_decoding_and_construction_isolate_nested_arrays():
    assert _run("isolation", command=["Hakuno", 1, [["1B"]]])["result"] is True


@pytest.mark.parametrize("partial", [False, True])
def test_direct_javascript_sparse_groups_cannot_be_serialized_as_null_card_entries(partial):
    assert _run("sparse", partial=partial)["result"] == {"read": True, "make": True, "edit": True, "decode": None, "clear": []}


@pytest.mark.parametrize("edit,expected", [
    ({"type": "add"}, [["1B", "2A"], ["3Q"], ["1B"]]),
    ({"type": "remove", "index": 0}, [["3Q"]]),
    ({"type": "move", "index": 0, "to": 1}, [["3Q"], ["1B", "2A"]]),
    ({"type": "add-card", "index": 0}, [["1B", "2A", "1B"], ["3Q"]]),
    ({"type": "add-card", "index": 1, "code": "S0"}, [["1B", "2A"], ["3Q", "S0"]]),
    ({"type": "update-card", "index": 0, "card": 1, "code": "1B"}, [["1B", "1B"], ["3Q"]]),
    ({"type": "remove-card", "index": 0, "card": 0}, [["2A"], ["3Q"]]),
    ({"type": "remove-card", "index": 1, "card": 0}, [["1B", "2A"]]),
    ({"type": "clear"}, []),
])
def test_hakuno_combination_edits_keep_order_and_remove_a_group_when_its_last_card_is_removed(edit, expected):
    assert _run("edit", needs=[["1B", "2A"], ["3Q"]], edit=edit)["result"] == expected


@pytest.mark.parametrize("edit", [None, {}, {"type": "unknown"}, {"type": "remove", "index": True},
                                {"type": "remove", "index": -1}, {"type": "remove", "index": 2},
                                {"type": "move", "index": 0, "to": 2}, {"type": "add-card", "index": 3},
                                {"type": "update-card", "index": 0, "card": 2, "code": "1B"},
                                {"type": "update-card", "index": 0, "card": True, "code": "1B"},
                                {"type": "update-card", "index": 0, "card": 0},
                                {"type": "add-card", "index": 0, "code": "S01"}])
def test_invalid_hakuno_edits_do_not_guess_indices_or_codes(edit):
    assert _run("edit", needs=[["1B"], ["2A"]], edit=edit)["error"]


def test_hakuno_combination_and_card_bounds_are_enforced_without_mutation():
    needs = [["1B"] for _ in range(1000)]
    assert len(_run("read", needs=needs)["result"]) == 1000
    assert _run("edit", needs=needs, edit={"type": "add"})["error"]
    assert _run("read", needs=needs + [[]])["error"]
    assert _run("edit", needs=[["1B"] * 5], edit={"type": "add-card", "index": 0})["error"]
    assert _run("edit", needs=[["1B"] * 5], edit={"type": "update-card", "index": 0, "card": 4, "code": "S0"})["result"] == [["1B"] * 4 + ["S0"]]


@pytest.mark.parametrize("needs", [None, "1B", {}, ["1B"], [[True]], [["S01"]], [["1B"] * 6]])
def test_malformed_needs_require_explicit_clear_and_are_never_reinterpreted(needs):
    assert _run("read", needs=needs)["error"]
    assert _run("edit", needs=needs, edit={"type": "add"})["error"]
    assert _run("edit", needs=needs, edit={"type": "clear"})["result"] == []


@pytest.mark.parametrize("skill,needs", [(None, []), (True, []), (2, []), (1.5, []), (1, None), (1, ["1B"]), (1, [["S01"]])])
def test_hakuno_construction_requires_explicit_original_parameters(skill, needs):
    assert _run("make", skill=skill, needs=needs)["error"]
