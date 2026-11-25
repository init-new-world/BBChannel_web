import json
from pathlib import Path
import shutil
import subprocess

import pytest

from webapp.services.script_data import ScriptDataService

NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="Node.js is not installed.")
MODULE = Path(__file__).resolve().parents[1] / "webapp" / "static" / "preset-strategy-visual.js"


def _run(code: str, payload: dict) -> dict:
    script = f"""
        import * as mod from {json.dumps(MODULE.as_uri())};
        import {{ readFileSync }} from 'node:fs';
        const input = JSON.parse(readFileSync(0, 'utf8'));
        {code}
    """
    res = subprocess.run(
        [NODE, "--input-type=module", "-e", script],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout)


def test_all_quick_strategy_templates_pass_backend_validation(tmp_path: Path):
    out = _run(
        """
        const built = [];
        for (const tpl of mod.STRATEGY_QUICK_TEMPLATES) {
          for (const slot of [1, 2, 3]) {
            built.push({ id: `${tpl.id}-${slot}`, entry: [{ tag: `${tpl.id}-${slot}`, strategy: tpl.build(slot) }] });
          }
        }
        process.stdout.write(JSON.stringify({ built }));
        """,
        {},
    )
    service = ScriptDataService(tmp_path)
    assert len(out["built"]) == 18
    for item in out["built"]:
        saved = service.save_strategy(item["id"], item["entry"])
        assert saved["validation"]["ok"] is True, f"{item['id']}: {saved['validation']}"


def test_card_preference_toggle_move_and_order_builders():
    out = _run(
        """
        const main2A = mod.buildMainAttackerOrder(2, "A");
        const allQ = mod.buildAllCardsByColorOrder("Q");
        const added = mod.toggleCardPreference(["1B"], "2A");
        const removed = mod.toggleCardPreference(["1B", "2A"], "1B");
        const keepLast = mod.toggleCardPreference(["2A"], "2A");
        const moved = mod.moveCardPreference(["1B", "2A", "3Q"], 2, -1);
        process.stdout.write(JSON.stringify({ main2A, allQ, added, removed, keepLast, moved }));
        """,
        {},
    )
    assert out["main2A"] == ["2A", "2B", "2Q", "1B", "3B", "1A", "3A", "1Q", "3Q"]
    assert out["allQ"] == ["1Q", "2Q", "3Q", "1B", "2B", "3B", "1A", "2A", "3A"]
    assert out["added"] == ["1B", "2A"]
    assert out["removed"] == ["2A"]
    assert out["keepLast"] == ["2A"]
    assert out["moved"] == ["1B", "3Q", "2A"]
