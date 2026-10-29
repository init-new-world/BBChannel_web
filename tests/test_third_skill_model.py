import json
from pathlib import Path
import shutil
import subprocess

import pytest

NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="Node.js is not installed.")
MODULE = Path(__file__).resolve().parents[1] / "webapp" / "static" / "third-skill-model.js"
OPTIONS = {"Barghest": [0, 1], "BBDubai": [0, 1], "Soujyuro": ["Q", "A", "B"], "Hakuno": ["T", "D", "R"]}


def _run(action, **payload):
    script = f"""
        import * as third from {json.dumps(MODULE.as_uri())};
        import {{ readFileSync }} from 'node:fs';
        const input = JSON.parse(readFileSync(0, 'utf8'));
        const before = JSON.stringify(input);
        let result, error = null;
        try {{
            if (input.action === 'decode') result = third.decodeThirdSkill(input.command);
            else if (input.action === 'options') {{
                const values = third.thirdSkillOptions(input.named);
                if (values) values.reverse().push('future');
                result = third.thirdSkillOptions(input.named);
            }} else result = third.makeThirdSkill(input.named, input.skill, input.option);
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


@pytest.mark.parametrize("named,skill,option", [(named, skill, option) for named, options in OPTIONS.items()
                                              for skill in (3, 6, 9) for option in options])
def test_original_third_skill_forms_round_trip_without_option_coercion(named, skill, option):
    command = [named, skill, option]
    assert _run("decode", command=command)["result"] == {"named": named, "skill": skill, "option": option, "target": None}
    made = _run("make", named=named, skill=skill, option=option)["result"]
    assert made == command
    assert type(made[2]) is type(option)


@pytest.mark.parametrize("named,options", OPTIONS.items())
def test_options_retain_original_order_and_cannot_be_mutated_by_a_caller(named, options):
    assert _run("options", named=named)["result"] == options


@pytest.mark.parametrize("named", [None, "Future", "barghest", "Kukulkan", "__proto__", "toString", 0, []])
def test_unknown_option_domains_are_not_guessed(named):
    assert _run("options", named=named)["result"] is None


@pytest.mark.parametrize("named", OPTIONS)
@pytest.mark.parametrize("skill", [0, 1, 2, 4, 5, 7, 8, 10, True, "3", 3.5])
def test_non_third_skill_positions_stay_unrecognized(named, skill):
    option = OPTIONS[named][0]
    assert _run("decode", command=[named, skill, option])["result"] is None
    assert _run("make", named=named, skill=skill, option=option)["error"]


@pytest.mark.parametrize("command", [
    None, "Barghest", [], ["Barghest"], ["Barghest", 3], ["Barghest", 3, 0, 1],
    ["Barghest", 3, True], ["BBDubai", 3, False], ["Barghest", 3, "0"], ["BBDubai", 3, "1"],
    ["Barghest", 3, 2], ["BBDubai", 3, -1], ["Barghest", 3, None], ["BBDubai", 3, 0.5],
    ["Soujyuro", 3, 1], ["Soujyuro", 3, "Quick"], ["Soujyuro", 3, "q"], ["Soujyuro", 3, "T"],
    ["Hakuno", 3, 0], ["Hakuno", 3, "A"], ["Hakuno", 3, "t"], ["Hakuno", 3, []],
    ["Hakuno", 1, [["1B"]]], ["Future", 3, 0], ["__proto__", 3, 0], ["toString", 3, 0],
])
def test_unknown_or_malformed_forms_are_not_normalized(command):
    assert _run("decode", command=command)["result"] is None


@pytest.mark.parametrize("named,option", [("Barghest", True), ("BBDubai", "1"), ("Barghest", None),
                                        ("Soujyuro", "T"), ("Hakuno", "Q"), ("Future", 0), (None, 0)])
def test_construction_rejects_wrong_option_types_or_families(named, option):
    assert _run("make", named=named, skill=3, option=option)["error"]
