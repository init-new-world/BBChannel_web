import json
from pathlib import Path
import shutil
import subprocess

import pytest

NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="Node.js is not installed.")
MODULE = Path(__file__).resolve().parents[1] / "webapp" / "static" / "skill-variants-model.js"
RULES = {"VanGoghMiner": (1, ["Q", "A", "B"]), "Dante": (2, ["A", "B"]), "Gyokuto": (2, ["All", "One"]),
         "Charlotte": (3, ["\u6280", "\u66b4", "\u5b9d"]), "Flora": (3, ["T", "D"]),
         "Prelati": (1, ["\u4e0d\u66ff\u6362", "\u66ff\u6362"]),
         "Lilith": (3, ["\u4e0d\u4ed8\u4e0e\u5373\u6b7b", "\u4ed8\u4e0e\u5373\u6b7b"]),
         "Masi": (1, ["\u65e0\u654c", "\u6bc5\u529b"])}


def _run(action, **payload):
    script = f"""
        import * as variants from {json.dumps(MODULE.as_uri())};
        import {{ readFileSync }} from 'node:fs';
        const input = JSON.parse(readFileSync(0, 'utf8'));
        const before = JSON.stringify(input);
        let result, error = null;
        try {{
            if (input.action === 'decode') result = variants.decodeSkillVariant(input.command);
            else if (input.action === 'available') result = variants.skillVariantAvailable(input.named, input.server);
            else if (input.action === 'options' || input.action === 'numbers') {{
                const lookup = input.action === 'options' ? variants.skillVariantOptions : variants.skillVariantNumbers;
                const values = lookup(input.named);
                if (values) values.reverse().push('future');
                result = lookup(input.named);
            }} else result = variants.makeSkillVariant(input.named, input.skill, input.option);
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


@pytest.mark.parametrize("named,skill,option", [(named, first + offset, option) for named, (first, options) in RULES.items()
                                              for offset in (0, 3, 6) for option in options])
def test_original_skill_variants_round_trip_at_only_the_original_skill_position(named, skill, option):
    command = [named, skill, option]
    assert _run("decode", command=command)["result"] == {"named": named, "skill": skill, "option": option, "target": None}
    assert _run("make", named=named, skill=skill, option=option)["result"] == command


@pytest.mark.parametrize("named,rule", RULES.items())
def test_variant_options_and_skill_numbers_are_ordered_isolated_copies(named, rule):
    first, options = rule
    assert _run("options", named=named)["result"] == options
    assert _run("numbers", named=named)["result"] == [first, first + 3, first + 6]


@pytest.mark.parametrize("server,expected", [("CH", True), ("JP", True), ("ch", True), ("jp", True),
                                           ("CNTW", False), ("cntw", False), (" CH ", False),
                                           ("Future", False), ("", False), (None, False), (0, False), ([], False)])
def test_only_chinese_and_japanese_servers_offer_new_charlotte_variant_selection(server, expected):
    assert _run("available", named="Charlotte", server=server)["result"] is expected
    assert _run("decode", command=["Charlotte", 3, "\u6280"])["result"] is not None


@pytest.mark.parametrize("server,expected", [("JP", True), ("jp", True), ("CH", False), ("ch", False),
                                           ("CNTW", False), ("cntw", False), (" JP ", False),
                                           ("Future", False), ("", False), (None, False), (0, False), ([], False)])
def test_only_japanese_server_offers_new_masi_variant_selection(server, expected):
    assert _run("available", named="Masi", server=server)["result"] is expected
    assert _run("decode", command=["Masi", 1, "\u65e0\u654c"])["result"] is not None


@pytest.mark.parametrize("named", ["VanGoghMiner", "Dante", "Gyokuto", "Flora", "Prelati", "Lilith"])
@pytest.mark.parametrize("server", ["CH", "JP", "CNTW", None])
def test_other_original_variant_routes_have_no_server_condition(named, server):
    assert _run("available", named=named, server=server)["result"] is True


@pytest.mark.parametrize("named", [None, "Future", "vangoGHMiner", "Kukulkan", "Hakuno", "__proto__", "constructor", "toString", 0, []])
def test_unknown_variant_names_do_not_inherit_rules(named):
    assert _run("options", named=named)["result"] is None
    assert _run("numbers", named=named)["result"] is None
    assert _run("available", named=named, server="CH")["result"] is False


@pytest.mark.parametrize("named,skill", [(named, skill) for named, (first, _options) in RULES.items()
                                       for skill in range(1, 10) if skill % 3 != first % 3])
def test_other_skill_positions_are_not_inferred_from_the_broader_backend_grammar(named, skill):
    option = RULES[named][1][0]
    assert _run("decode", command=[named, skill, option])["result"] is None
    assert _run("make", named=named, skill=skill, option=option)["error"]


@pytest.mark.parametrize("command", [None, "Dante", [], ["Dante"], ["Dante", 2], ["Dante", 2, "A", 1],
                                     ["VanGoghMiner", True, "Q"], ["Dante", 2.5, "A"], ["Gyokuto", "2", "All"],
                                     ["Charlotte", 0, "\u6280"], ["Flora", 12, "T"], ["Flora", -3, "T"],
                                     ["Dante", 2, True], ["Gyokuto", 2, 0], ["Charlotte", 3, "Skill"],
                                     ["VanGoghMiner", 1, "Quick"], ["Dante", 2, "Q"], ["Gyokuto", 2, "all"],
                                     ["Charlotte", 3, "A"], ["Flora", 3, "R"], ["Flora", 3, None],
                                     ["Flora", 3, []], ["Future", 3, "T"], ["__proto__", 3, "T"]])
def test_malformed_or_cross_family_variant_forms_stay_unrecognized(command):
    assert _run("decode", command=command)["result"] is None


@pytest.mark.parametrize("named,skill,option", [("Dante", True, "A"), ("Dante", 2, "Q"), ("Gyokuto", 2, True),
                                             ("VanGoghMiner", 1, "1"), ("Charlotte", 3, "A"), ("Flora", 3, "R"), ("Future", 3, "T")])
def test_variant_construction_rejects_wrong_types_and_option_domains(named, skill, option):
    assert _run("make", named=named, skill=skill, option=option)["error"]
