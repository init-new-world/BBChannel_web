import json
from pathlib import Path
import shutil
import subprocess

import pytest

from webapp.automation.program import compile_skill_command


NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="Node.js is not installed.")
MODULE = Path(__file__).resolve().parents[1] / "webapp" / "static" / "wizard-special-skills.js"


def _run(script_body: str, payload: dict):
    script = f"""
        import * as wizardSkills from {json.dumps(MODULE.as_uri())};
        import {{ readFileSync }} from 'node:fs';
        const input = JSON.parse(readFileSync(0, 'utf8'));
        {script_body}
    """
    response = subprocess.run(
        [NODE, "--input-type=module", "-e", script],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert response.returncode == 0, response.stderr
    return json.loads(response.stdout)


ALL_SPECIAL_CASES = [
    ("太空伊什塔尔", 0, 1, "CH", "special-np", 1, None, [-2, 1]),
    ("太空伊什塔尔", 1, 1, "JP", "special-np", 3, None, [-5, 3]),
    ("卫宫", 0, 2, "CH", "special-np", 1, None, [-3, 1]),
    ("卫宫", 2, 2, "CNTW", "special-np", 2, None, [-9, 2]),
    ("库库尔坎", 0, 0, "CH", "kukulkan", 0, None, ["Kukulkan", 1, 0]),
    ("库库尔坎", 0, 1, "CH", "kukulkan", 1, 2, ["Kukulkan", 2, 1, 2]),
    ("库库尔坎", 2, 2, "JP", "kukulkan", 1, None, ["Kukulkan", 9, 1]),
    ("UDK-巴格斯特", 0, 2, "CH", "third", 0, None, ["Barghest", 3, 0]),
    ("UDK-巴格斯特", 1, 2, "JP", "third", 1, None, ["Barghest", 6, 1]),
    ("静希草十郎", 0, 2, "CH", "third", "B", None, ["Soujyuro", 3, "B"]),
    ("BB迪拜", 0, 2, "CH", "third", 1, None, ["BBDubai", 3, 1]),
    ("岸波白野(女性)", 0, 2, "CH", "third", "R", None, ["Hakuno", 3, "R"]),
    ("岸波白野(男性)", 1, 2, "JP", "third", "T", None, ["Hakuno", 6, "T"]),
    ("岸波白野(女性)", 0, 0, "CH", "hakuno-needs", [], None, ["Hakuno", 1, []]),
    ("岸波白野(男性)", 2, 0, "JP", "hakuno-needs", [], None, ["Hakuno", 7, []]),
    ("梵高〔矿工〕", 0, 0, "CH", "variant", "Q", None, ["VanGoghMiner", 1, "Q"]),
    ("但丁·阿利吉耶里", 1, 1, "CH", "variant", "B", None, ["Dante", 5, "B"]),
    ("玉兔", 2, 1, "JP", "variant", "One", None, ["Gyokuto", 8, "One"]),
    ("夏洛特·科黛", 0, 2, "CH", "variant", "技", None, ["Charlotte", 3, "技"]),
    ("夏洛特·科黛", 1, 2, "JP", "variant", "宝", None, ["Charlotte", 6, "宝"]),
    ("芙萝拉", 0, 2, "CH", "variant", "D", None, ["Flora", 3, "D"]),
    ("弗朗索瓦·普勒拉蒂", 0, 0, "CH", "variant", "不替换", None, ["Prelati", 1, "不替换"]),
    ("弗朗索瓦·普勒拉蒂", 0, 0, "CH", "variant", "替换", None, ["Prelati", 1, "替换"]),
    ("弗兰切斯卡·普勒拉蒂", 2, 0, "JP", "variant", "替换", None, ["Prelati", 7, "替换"]),
    ("莉莉丝(Rider)", 0, 2, "CH", "variant", "付与即死", None, ["Lilith", 3, "付与即死"]),
    ("马嘶", 0, 0, "JP", "variant", "无敌", None, ["Masi", 1, "无敌"]),
    ("马嘶", 1, 0, "JP", "variant", "毅力", None, ["Masi", 4, "毅力"]),
]


@pytest.mark.parametrize(
    "name,slot,skill_idx,server,expected_kind,option,target,expected_cmd",
    ALL_SPECIAL_CASES,
)
def test_wizard_resolves_builds_and_compiles_all_special_servant_skills(
    name, slot, skill_idx, server, expected_kind, option, target, expected_cmd
):
    result = _run(
        """
        const spec = wizardSkills.resolveWizardSpecialSkill(input.name, input.slot, input.skill_idx, input.server);
        const cmd = spec ? wizardSkills.buildWizardSpecialCommand(spec, input.option, input.target) : null;
        const skillNum = cmd ? wizardSkills.extractServantSkillNumber(cmd) : null;
        const formatted = cmd ? wizardSkills.formatSpecialSkillCommand(cmd, {
            skillName: (n) => `Skill#${n}`,
            slotLabel: (s) => `Slot#${s}`,
            translate: (k) => k,
        }) : null;
        process.stdout.write(JSON.stringify({ spec, cmd, skillNum, formatted }));
        """,
        {
            "name": name,
            "slot": slot,
            "skill_idx": skill_idx,
            "server": server,
            "option": option,
            "target": target,
        },
    )

    assert result["spec"] is not None
    assert result["spec"]["kind"] == expected_kind
    assert result["cmd"] == expected_cmd
    assert result["skillNum"] == slot * 3 + skill_idx + 1
    assert isinstance(result["formatted"], str) and f"Skill#{slot * 3 + skill_idx + 1}" in result["formatted"]

    # Backend program compiler MUST accept every command emitted by the wizard!
    compiled = compile_skill_command(result["cmd"])
    assert compiled["supported"] is True, compiled


@pytest.mark.parametrize(
    "name,skill_idx,server",
    [
        ("夏洛特·科黛", 2, "CNTW"),
        ("马嘶", 0, "CH"),
        ("马嘶", 0, "CNTW"),
        ("弗朗索瓦·普勒拉蒂", 1, "CH"),
        ("弗朗索瓦·普勒拉蒂", 2, "CH"),
        ("莉莉丝(Rider)", 0, "CH"),
        ("莉莉丝(Rider)", 1, "CH"),
        ("太空伊什塔尔", 0, "CH"),
        ("太空伊什塔尔", 2, "CH"),
        ("卫宫", 1, "CH"),
        ("光之高扬斯卡娅", 0, "CH"),
    ],
)
def test_wizard_respects_server_gates_and_non_special_skill_slots(name, skill_idx, server):
    result = _run(
        """
        const spec = wizardSkills.resolveWizardSpecialSkill(input.name, 0, input.skill_idx, input.server);
        process.stdout.write(JSON.stringify({ spec }));
        """,
        {"name": name, "skill_idx": skill_idx, "server": server},
    )
    assert result["spec"] is None


def test_wizard_lineup_tracks_order_change_across_waves_and_within_wave():
    config = {
        "round1_turns": 1,
        "round1_turn0_skill": [1, [12, 1, 4], ["Prelati", 1, "替换"]],
        "round2_turns": 1,
        "round2_turn0_skill": [4],
    }
    result = _run(
        """
        const w1_start = wizardSkills.computeLineupBefore(input.config, 1, 0);
        const w1_before_swap = wizardSkills.computeLineupBefore(input.config, 1, 1);
        const w1_after_swap = wizardSkills.computeLineupBefore(input.config, 1, 2);
        const w2_start = wizardSkills.computeLineupBefore(input.config, 2, 0);
        process.stdout.write(JSON.stringify({ w1_start, w1_before_swap, w1_after_swap, w2_start }));
        """,
        {"config": config},
    )
    assert result["w1_start"] == [0, 1, 2, 3, 4, 5]
    assert result["w1_before_swap"] == [0, 1, 2, 3, 4, 5]
    assert result["w1_after_swap"] == [3, 1, 2, 0, 4, 5]
    assert result["w2_start"] == [3, 1, 2, 0, 4, 5]
