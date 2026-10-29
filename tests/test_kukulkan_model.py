import json
from pathlib import Path
import shutil
import subprocess

import pytest

NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="Node.js is not installed.")
MODULE = Path(__file__).resolve().parents[1] / "webapp" / "static" / "kukulkan-model.js"


def _run(action, **payload):
    script = f"""
        import * as kukulkan from {json.dumps(MODULE.as_uri())};
        import {{ readFileSync }} from 'node:fs';
        const input = JSON.parse(readFileSync(0, 'utf8'));
        const before = JSON.stringify(input);
        let result, error = null;
        try {{
            result = input.action === 'decode' ? kukulkan.decodeKukulkan(input.command)
                : input.action === 'target' ? kukulkan.kukulkanNeedsTarget(input.skill)
                : kukulkan.makeKukulkan(input.skill, input.option, input.target);
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


VALID = [(skill, option, target) for skill in range(1, 10) for option in (0, 1)
         for target in ((1, 2, 3) if skill % 3 == 2 else (None,))]


@pytest.mark.parametrize("skill,option,target", VALID)
def test_original_kukulkan_forms_keep_star_option_and_required_second_skill_target(skill, option, target):
    command = ["Kukulkan", skill, option] + ([target] if target is not None else [])
    assert _run("decode", command=command)["result"] == {"named": "Kukulkan", "skill": skill, "option": option, "target": target}
    assert _run("make", skill=skill, option=option, target=target)["result"] == command


@pytest.mark.parametrize("skill", range(1, 10))
def test_only_second_skill_positions_require_a_servant_target(skill):
    assert _run("target", skill=skill)["result"] is (skill % 3 == 2)


@pytest.mark.parametrize("command", [
    None, "Kukulkan", ["Kukulkan"], ["Kukulkan", True, 0], ["Kukulkan", 0, 0], ["Kukulkan", 10, 0],
    ["Kukulkan", 1, True], ["Kukulkan", 1, 2], ["Kukulkan", 1, "1"], ["Kukulkan", 2, 1],
    ["Kukulkan", 2, 1, None], ["Kukulkan", 2, 1, True], ["Kukulkan", 2, 1, 0], ["Kukulkan", 2, 1, 4],
    ["Kukulkan", 1, 1, 3], ["Kukulkan", 2, 1, 1, 2], ["kukulkan", 1, 1], ["Future", 1, 1],
    ["Kukulkan", 1.5, 1], ["Kukulkan", 1, 0.5], ["Kukulkan", 2, 1, 1.5],
])
def test_non_original_or_malformed_kukulkan_commands_remain_unrecognized(command):
    assert _run("decode", command=command)["result"] is None


@pytest.mark.parametrize("skill,option,target", [
    (0, 0, None), (10, 1, None), (True, 1, None), (1, True, None), (1, "1", None), (1, None, None),
    (1, 1, 1), (2, 0, None), (2, 1, False), (2, 1, 4), (2, 1, "1"),
])
def test_kukulkan_construction_does_not_guess_or_coerce_invalid_parameters(skill, option, target):
    assert _run("make", skill=skill, option=option, target=target)["error"]
