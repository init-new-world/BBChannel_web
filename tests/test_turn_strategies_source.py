import json
from pathlib import Path
import shutil
import subprocess

import pytest

NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="Node.js is not installed.")
MODULE = Path(__file__).resolve().parents[1] / "webapp" / "static" / "turn-strategies-source.js"


def _run(action, source, target="round1_turn0_strategy", preset=None):
    script = f"""
        import * as strategies from {json.dumps(MODULE.as_uri())};
        import {{ readFileSync }} from 'node:fs';
        const input = JSON.parse(readFileSync(0, 'utf8'));
        try {{
            const result = input.action === 'inspect' ? strategies.inspectStrategySource(input.source, input.target)
                : input.action === 'clear' ? strategies.clearStrategySource(input.source, input.target)
                : strategies.applyStrategySource(input.source, input.target, input.preset);
            process.stdout.write(JSON.stringify({{ result, error: null }}));
        }} catch (error) {{ process.stdout.write(JSON.stringify({{ error: error.message }})); }}
    """
    response = subprocess.run([NODE, "--input-type=module", "-e", script],
                              input=json.dumps({"action": action, "source": source, "target": target, "preset": preset}),
                              text=True, capture_output=True, timeout=10, check=False)
    assert response.returncode == 0, response.stderr
    return json.loads(response.stdout)


def _preset(source=None):
    detail = {"validation": {"ok": True}, "entries": [{"tag": "One", "strategy": {"marker": "one"}}]}
    if source is not None:
        detail["source"] = source
        try:
            parsed = json.loads(source)
            if isinstance(parsed, list):
                detail["entries"] = parsed
        except json.JSONDecodeError:
            pass
    return detail


@pytest.mark.parametrize("target", ["round1_turn0_strategy", "round2_extraStrategy"])
@pytest.mark.parametrize("existing", [False, True])
def test_strategy_application_keeps_typed_values_in_both_script_and_selected_preset(target, existing):
    prefix = '{"metadata":{"float":1.0,"large":9007199254740993},"round1_turn0_skill":[1.0]'
    source = prefix + (',"' + target + '":[{"old":true}]' if existing else '') + '}'
    raw = '[{"tag":"One","strategy":{"float":2.0,"large":9007199254740995,"marker":"one"}},' \
          '{"tag":"Two","strategy":{"float":3e0,"marker":"two"}}]'
    result = _run("apply", source, target, _preset(raw))
    assert result["error"] is None
    saved = json.loads(result["result"])
    assert type(saved["metadata"]["float"]) is float
    assert saved["metadata"]["large"] == 9007199254740993
    assert type(saved["round1_turn0_skill"][0]) is float
    assert saved[target] == [{"float": 2.0, "large": 9007199254740995, "marker": "one"}, {"float": 3.0, "marker": "two"}]
    assert type(saved[target][0]["float"]) is float
    assert type(saved[target][1]["float"]) is float
    assert '3e0' in result["result"]


def test_strategy_clear_only_replaces_the_target_value_and_retains_its_empty_field():
    prefix = '{"metadata":1.0,"round1_turn0_skill":[1.0],"round1_turn0_strategy":'
    suffix = ',"round2_extraStrategy":[{"keep":true}]}'
    source = prefix + '[{"old":true}]' + suffix
    assert _run("clear", source)["result"] == prefix + '[]' + suffix


@pytest.mark.parametrize("value,can_clear", [(None, False), ([], False), ([{}], True), ({"future": True}, True), (False, True)])
def test_strategy_target_inspection_preserves_legacy_confirmation_rules(value, can_clear):
    source = json.dumps({"round1_turn0_strategy": value})
    assert _run("inspect", source)["result"] == {"field": "round1_turn0_strategy", "canClear": can_clear}


@pytest.mark.parametrize("source", [
    '{"round1_turn0_strategy":[],"round1_turn0_strategy":[{}]}',
    '{"round1_turn0_strategy":[],"round1_turn0_\\u0073trategy":[{}]}',
    '{"round1_turn0_strategy":[],}', '[]', 'null', '{',
])
def test_ambiguous_or_invalid_script_source_never_applies_or_clears(source):
    assert _run("inspect", source)["error"]
    assert _run("apply", source, preset=_preset())["error"]
    assert _run("clear", source)["error"]


@pytest.mark.parametrize("target", [None, "", "round01_turn0_strategy", "round1_turn01_strategy", "round1_extraSkill",
                                    "round9007199254740992_extraStrategy", "round1_turn9007199254740992_strategy"])
def test_invalid_strategy_targets_never_rewrite_json(target):
    assert _run("apply", "{}", target, _preset())["error"]
    assert _run("clear", "{}", target)["error"]


@pytest.mark.parametrize("raw", [
    '[]', '{}', '[null]', '[{"strategy":[]}]', '[{"strategy":{},{"bad":true}}]',
    '[{"strategy":{},"strategy":{"other":true}}]', '[{"strategy":{},"\\u0073trategy":{}}]',
    '[{"strategy":{}},]', '[/*comment*/{"strategy":{}}]',
])
def test_malformed_or_ambiguous_preset_source_is_not_applied(raw):
    assert _run("apply", '{}', preset=_preset(raw))["error"]


def test_legacy_strategy_response_without_source_remains_supported():
    result = _run("apply", '{"metadata":1.0}', preset=_preset())
    assert result["error"] is None
    assert json.loads(result["result"]) == {"metadata": 1.0, "round1_turn0_strategy": [{"marker": "one"}]}
    assert type(json.loads(result["result"])["metadata"]) is float


@pytest.mark.parametrize("preset", [{}, {"validation": {"ok": False}, "entries": [{}]},
                                   {"validation": {"ok": True}, "entries": []},
                                   {"validation": {"ok": True}, "entries": [{"strategy": None}]}])
def test_invalid_or_empty_strategy_details_are_rejected(preset):
    assert _run("apply", '{}', preset=preset)["error"]
