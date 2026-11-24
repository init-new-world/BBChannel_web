from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


STATIC_DIR = Path(__file__).resolve().parents[1] / "webapp" / "static"


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is required to test ES module gesture engine.")
def test_screen_touch_gesture_engine_anti_jitter_and_realtime_modes():
    script = f"""
import assert from "node:assert/strict";
import {{ createTouchGestureEngine }} from {str((STATIC_DIR / "screen-touch.js").as_uri())!r};

function createHarness(overrides = {{}}) {{
  let clock = 1000;
  let nextTimerId = 1;
  const timers = new Map();
  const events = [];

  const engine = createTouchGestureEngine({{
    now: () => clock,
    setTimer: (fn, ms) => {{
      const id = nextTimerId++;
      timers.set(id, {{ fn, due: clock + ms }});
      return id;
    }},
    clearTimer: (id) => {{
      timers.delete(id);
    }},
    onTap: (e) => events.push(["tap", e]),
    onLiveDown: (e) => events.push(["down", e]),
    onLiveMove: (e) => events.push(["move", e]),
    onLiveUp: (e) => events.push(["up", e]),
    onLiveCancel: (e) => events.push(["cancel", e]),
    onSwipeFallback: (e) => events.push(["swipe_fallback", e]),
    onPickDrag: (e) => events.push(["pick_drag", e]),
    ...overrides,
  }});

  function advance(ms) {{
    const target = clock + ms;
    while (true) {{
      let soonestId = null;
      let soonestDue = Infinity;
      for (const [id, entry] of timers.entries()) {{
        if (entry.due <= target && entry.due < soonestDue) {{
          soonestDue = entry.due;
          soonestId = id;
        }}
      }}
      if (soonestId === null) break;
      const entry = timers.get(soonestId);
      timers.delete(soonestId);
      clock = entry.due;
      entry.fn();
    }}
    clock = target;
  }}

  return {{ engine, events, advance, getClock: () => clock }};
}}

// 1. Quick click with 7px hand jitter (< 10px slop) -> clean TAP at press origin
{{
  const h = createHarness();
  assert.equal(h.engine.pointerDown({{ pointerId: 1, clientX: 100, clientY: 200, deviceX: 500, deviceY: 300, controlEnabled: true }}), true);
  h.advance(60);
  h.engine.pointerMove({{ pointerId: 1, clientX: 105, clientY: 205, deviceX: 515, deviceY: 315 }});
  h.advance(60);
  h.engine.pointerUp({{ pointerId: 1, clientX: 106, clientY: 204, deviceX: 518, deviceY: 312 }});
  assert.deepEqual(h.events.map(([k]) => k), ["tap"]);
  assert.equal(h.events[0][1].x, 500);
  assert.equal(h.events[0][1].y, 300);
}}

// 2. Slow hesitant click (380ms < 420ms, 6px jitter) -> STILL clean TAP, never false long-press
{{
  const h = createHarness();
  h.engine.pointerDown({{ pointerId: 1, clientX: 200, clientY: 200, deviceX: 600, deviceY: 400, controlEnabled: true }});
  h.advance(200);
  h.engine.pointerMove({{ pointerId: 1, clientX: 204, clientY: 204, deviceX: 610, deviceY: 410 }});
  h.advance(180);
  h.engine.pointerUp({{ pointerId: 1, clientX: 204, clientY: 204, deviceX: 610, deviceY: 410 }});
  assert.deepEqual(h.events.map(([k]) => k), ["tap"]);
  assert.equal(h.events[0][1].x, 600);
}}

// 3. Hardware microswitch bounce guard (< 45ms at same spot ignored; >= 55ms accepted)
{{
  const h = createHarness();
  assert.equal(h.engine.pointerDown({{ pointerId: 1, clientX: 100, clientY: 100, deviceX: 100, deviceY: 100, controlEnabled: true }}), true);
  h.advance(50);
  h.engine.pointerUp({{ pointerId: 1, clientX: 100, clientY: 100, deviceX: 100, deviceY: 100 }});
  h.advance(20);
  assert.equal(h.engine.pointerDown({{ pointerId: 2, clientX: 102, clientY: 101, deviceX: 102, deviceY: 101, controlEnabled: true }}), false);
  h.advance(40);
  assert.equal(h.engine.pointerDown({{ pointerId: 3, clientX: 102, clientY: 101, deviceX: 102, deviceY: 101, controlEnabled: true }}), true);
  h.advance(50);
  h.engine.pointerUp({{ pointerId: 3, clientX: 102, clientY: 101, deviceX: 102, deviceY: 101 }});
  assert.equal(h.events.filter(([k]) => k === "tap").length, 2);
}}

// 4. Real-time long press: live DOWN at 420ms, ignores 14px tremor (< 20px), live UP on release
{{
  const h = createHarness();
  h.engine.pointerDown({{ pointerId: 1, clientX: 300, clientY: 300, deviceX: 700, deviceY: 450, controlEnabled: true }});
  h.advance(419);
  assert.equal(h.events.length, 0);
  h.advance(1);
  assert.deepEqual(h.events.map(([k]) => k), ["down"]);
  assert.equal(h.events[0][1].mode, "long_press");
  // Slight 14px hand tremor while holding -> ignored!
  h.engine.pointerMove({{ pointerId: 1, clientX: 310, clientY: 310, deviceX: 720, deviceY: 470 }});
  h.advance(300);
  assert.equal(h.events.length, 1);
  h.engine.pointerUp({{ pointerId: 1, clientX: 310, clientY: 310, deviceX: 720, deviceY: 470 }});
  assert.deepEqual(h.events.map(([k]) => k), ["down", "up"]);
  assert.equal(h.events[1][1].x, 700);
  assert.equal(h.events[1][1].y, 450);
}}

// 5. Real-time long-press-then-drag (>= 20px intentional move while holding)
{{
  const h = createHarness();
  h.engine.pointerDown({{ pointerId: 1, clientX: 300, clientY: 300, deviceX: 700, deviceY: 450, controlEnabled: true }});
  h.advance(450);
  h.engine.pointerMove({{ pointerId: 1, clientX: 330, clientY: 300, deviceX: 760, deviceY: 450 }});
  h.advance(60);
  h.engine.pointerUp({{ pointerId: 1, clientX: 360, clientY: 300, deviceX: 820, deviceY: 450 }});
  assert.deepEqual(h.events.map(([k]) => k), ["down", "move", "move", "up"]);
  assert.equal(h.events[3][1].x, 820);
}}

// 6. Real-time drag: moving >= 10px cancels long press even if paused 800ms mid-drag
{{
  const h = createHarness();
  h.engine.pointerDown({{ pointerId: 1, clientX: 100, clientY: 100, deviceX: 200, deviceY: 200, controlEnabled: true }});
  h.advance(30);
  h.engine.pointerMove({{ pointerId: 1, clientX: 115, clientY: 100, deviceX: 240, deviceY: 200 }});
  assert.deepEqual(h.events.map(([k]) => k), ["down", "move"]);
  assert.equal(h.events[0][1].mode, "drag");
  assert.equal(h.events[0][1].x, 200);
  assert.equal(h.events[1][1].x, 240);
  // Pause 800ms mid-drag -> must stay in dragging state, never fire long_press!
  h.advance(800);
  assert.equal(h.engine.getState().phase, "dragging");
  assert.equal(h.events.length, 2);
  // Rapid micro moves get throttled cleanly
  h.engine.pointerMove({{ pointerId: 1, clientX: 130, clientY: 100, deviceX: 280, deviceY: 200 }});
  h.advance(10);
  h.engine.pointerMove({{ pointerId: 1, clientX: 145, clientY: 100, deviceX: 320, deviceY: 200 }});
  h.advance(30);
  h.engine.pointerUp({{ pointerId: 1, clientX: 160, clientY: 100, deviceX: 360, deviceY: 200 }});
  assert.equal(h.events.at(-1)[0], "up");
  assert.equal(h.events.at(-1)[1].x, 360);
}}

// 7. Blur / Escape cancel while holding emits live cancel immediately
{{
  const h = createHarness();
  h.engine.pointerDown({{ pointerId: 1, clientX: 100, clientY: 100, deviceX: 200, deviceY: 200, controlEnabled: true }});
  h.advance(500);
  h.engine.cancel("blur");
  assert.deepEqual(h.events.map(([k]) => k), ["down", "cancel"]);
  assert.equal(h.engine.getState().phase, "idle");
}}

// 8. Legacy backend fallback (liveTouchSupported = false) falls back to swipe cleanly
{{
  const h = createHarness({{ liveTouchSupported: false }});
  h.engine.pointerDown({{ pointerId: 1, clientX: 100, clientY: 100, deviceX: 200, deviceY: 200, controlEnabled: true }});
  h.advance(600);
  h.engine.pointerUp({{ pointerId: 1, clientX: 100, clientY: 100, deviceX: 200, deviceY: 200 }});
  assert.deepEqual(h.events.map(([k]) => k), ["swipe_fallback"]);
  assert.equal(h.events[0][1].mode, "long_press");
  assert.equal(h.events[0][1].durationMs, 600);
}}

// 9. Coordinate pick mode (controlEnabled = false): tap picks point, drag picks swipe coords
{{
  const h = createHarness();
  h.engine.pointerDown({{ pointerId: 1, clientX: 50, clientY: 50, deviceX: 100, deviceY: 150, controlEnabled: false }});
  h.advance(40);
  h.engine.pointerMove({{ pointerId: 1, clientX: 120, clientY: 50, deviceX: 300, deviceY: 150 }});
  h.advance(200);
  h.engine.pointerUp({{ pointerId: 1, clientX: 120, clientY: 50, deviceX: 300, deviceY: 150 }});
  assert.deepEqual(h.events.map(([k]) => k), ["pick_drag"]);
  assert.equal(h.events[0][1].x1, 100);
  assert.equal(h.events[0][1].x2, 300);
}}

console.log("ALL 9 GESTURE ENGINE SCENARIOS PASSED");
"""
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    assert "ALL 9 GESTURE ENGINE SCENARIOS PASSED" in result.stdout
