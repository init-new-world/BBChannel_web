import json
from pathlib import Path
import shutil
import subprocess

import pytest

NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="Node.js is not installed.")
MODULE = Path(__file__).resolve().parents[1] / "webapp" / "static" / "special-skills-model.js"


def _run(action, **payload):
    script = f"""
        import * as special from {json.dumps(MODULE.as_uri())};
        import {{ readFileSync }} from 'node:fs';
        const input = JSON.parse(readFileSync(0, 'utf8'));
        const before = JSON.stringify(input);
        let result, error = null;
        try {{
            if (input.action === 'colors') result = special.specialSkillColors(input.skill);
            else if (input.action === 'decode') result = special.decodeSpecialSkill(input.command);
            else if (input.action === 'choice') result = special.specialSkillChoice(input.command, input.skill);
            else result = special.makeSpecialSkill(input.skill, input.choice);
        }} catch (failure) {{ error = failure.message; }}
        process.stdout.write(JSON.stringify({{ result, error, unchanged: before === JSON.stringify(input) }}));
    """
    response = subprocess.run([NODE, "--input-type=module", "-e", script], input=json.dumps({"action": action, **payload}),
                              text=True, capture_output=True, timeout=10, check=False)
    assert response.returncode == 0, response.stderr
    result = json.loads(response.stdout)
    assert result["unchanged"] is True
    return result


@pytest.mark.parametrize("skill", [-2, -3, -5, -6, -8, -9])
def test_special_skill_choices_match_original_ishtar_and_emiya_order(skill):
    assert _run("colors", skill=skill)["result"] == (["Arts", "Buster"] if abs(skill) % 3 == 0 else ["Quick", "Arts", "Buster"])


@pytest.mark.parametrize("skill,choice", [(-skill, choice) for skill in (2, 3, 5, 6, 8, 9) for choice in range(1, 3 if skill % 3 == 0 else 4)])
def test_special_skill_pairs_decode_and_construct_without_changing_input(skill, choice):
    assert _run("decode", command=[skill, choice])["result"] == {"skill": skill, "target": None, "choice": choice}
    assert _run("make", skill=skill, choice=choice)["result"] == [skill, choice]


@pytest.mark.parametrize("command", [-2, [-2], [-2, None], [-2, True], [-2, "1"], [-2, 0], [-2, 4], [-3, 3],
                                     [-1, 1], [-4, 1], [-7, 1], [-10, 1], [1, 1], [-2, 1, 2], {"skill": -2}, [-2.5, 1], [-2, 1.5]])
def test_malformed_special_commands_never_coerce_to_a_color_choice(command):
    assert _run("decode", command=command)["result"] is None


@pytest.mark.parametrize("skill,choice", [(0, 1), (-1, 1), (-10, 1), (True, 1), (None, 1), (-2, True), (-2, None), (-3, 3), (-2, "2")])
def test_invalid_special_skill_or_color_is_rejected(skill, choice):
    assert _run("make", skill=skill, choice=choice)["error"]


@pytest.mark.parametrize("command,skill,choice", [
    ([-2, 2], -3, 1), ([-2, 3], -3, 2), ([-3, 1], -2, 2), ([-3, 2], -2, 3),
    ([-2, 1], -3, 1), ([-2, 3], -5, 3), (None, -2, 1), (1, -3, 1),
])
def test_switching_special_skill_positions_preserves_the_color_name_when_available(command, skill, choice):
    assert _run("choice", command=command, skill=skill)["result"] == choice


def test_selecting_colors_for_a_non_special_skill_is_rejected():
    assert _run("choice", command=[-2, 1], skill=1)["error"]
