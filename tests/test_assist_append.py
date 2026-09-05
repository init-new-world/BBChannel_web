from io import BytesIO
from types import SimpleNamespace

import pytest
from PIL import Image, ImageDraw

from webapp.automation.assist import create_assist_handler
from webapp.services.assist import AssistRecognizer
from webapp.services.recognition import RecognitionService
from webapp.services.resources import ResourceService


def _png(image):
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


@pytest.fixture
def append_recognizer(tmp_path):
    pytest.importorskip("cv2")
    assets = tmp_path / "assets"
    templates = {}
    for server in ("CH", "JP", "CNTW"):
        directory = assets / "battle" / server
        directory.mkdir(parents=True)
        for view, color in (("main", (240, 220, 50)), ("append", (30, 220, 250))):
            template = Image.new("RGB", (90, 24), color)
            draw = ImageDraw.Draw(template)
            draw.text((5, 5), view, fill="black")
            draw.rectangle((1, 1, 88, 22), outline="white")
            template.save(directory / f"{view}_skill.png")
            templates[view] = template.resize((60, 16), Image.Resampling.LANCZOS)
    for prefix in ("assist/full_skill", "assist/full_skill/CNTW"):
        directory = assets / prefix
        directory.mkdir(parents=True)
        for level, color in ((5, "red"), (8, "blue"), (10, "green")):
            template = Image.new("RGB", (18, 18), color)
            draw = ImageDraw.Draw(template)
            draw.text((2, 3), str(level), fill="white")
            stem = "10" if level == 10 else f"num{level}"
            template.save(directory / f"{stem}.png")
            templates[level] = template.resize((12, 12), Image.Resampling.LANCZOS)
    resources = ResourceService(assets, tmp_path / "data")
    return AssistRecognizer(resources, RecognitionService(resources)), templates


@pytest.mark.parametrize("server,levels", [
    ("CH", [5, 0, 8, 0, 10]), ("JP", [0, 8, 0, 10, 5]), ("CNTW", [5, 8, 10]),
])
def test_append_levels_match_each_slot_and_ignore_unrequested_slots(append_recognizer, server, levels):
    recognizer, templates = append_recognizer
    screen = Image.new("RGB", (1280, 720), (20, 25, 35))
    screen.paste(templates["append"], (850, 236))
    spacing = 63 if server == "CNTW" else 52.5
    for index, level in enumerate(levels):
        if level:
            screen.paste(templates[level], (round((1158 + index * spacing) * 1280 / 1788) + 5, 280))
    # This valid-looking digit belongs to a different support row.
    screen.paste(templates[10], (834, 500))
    candidate = {"anchor": [100, 200], "scale": 1.0, "checks": {}}
    result = recognizer.check_append_skills(_png(screen), candidate, levels, server=server, threshold=0.9)
    assert result["matched"]
    assert result["levels"] == [level or None for level in levels]
    too_high = [10] * len(levels)
    assert not recognizer.check_append_skills(_png(screen), candidate, too_high, server=server)["matched"]


def test_append_check_rejects_main_view_and_clipped_support_row(append_recognizer):
    recognizer, templates = append_recognizer
    screen = Image.new("RGB", (1280, 720), (20, 25, 35))
    screen.paste(templates["main"], (850, 236))
    candidate = {"anchor": [100, 200], "scale": 1.0}
    assert not recognizer.check_append_skills(_png(screen), candidate, [5, 0, 0, 0, 0], server="CH")["matched"]
    assert recognizer.match_skill_view(_png(screen), "CH")["view"] == "main"
    screen.paste(templates["append"], (850, 680))
    candidate["anchor"] = [100, 660]
    assert not recognizer.check_append_skills(_png(screen), candidate, [5, 0, 0, 0, 0], server="CH")["matched"]


@pytest.mark.parametrize("initial_view", ["main", "append"])
@pytest.mark.parametrize("matching", [True, False])
@pytest.mark.parametrize("row_shift", [0, 25])
def test_assist_handler_filters_append_levels_and_restores_main_view(initial_view, matching, row_shift):
    state = {"view": initial_view}
    taps = []
    checked = []
    recognition_count = 0
    candidates = [{"anchor": [100, y], "scale": 1.0, "checks": {}} for y in (200, 450)]

    class Device:
        def snapshot(self):
            return state["view"].encode()

        def tap(self, x, y):
            taps.append((x, y))
            if (x, y) == (847, 130):
                state["view"] = "append" if state["view"] == "main" else "main"
            else:
                assert state["view"] == "main"
                state["view"] = "team"
            return SimpleNamespace(to_dict=lambda: {"ok": True})

    class Recognizer:
        def match_reconnect(self, *_args):
            return SimpleNamespace(matched=False)

        match_not_available = match_reconnect
        match_no_assist = match_reconnect

        def match_skill_view(self, screenshot, server):
            return {"view": screenshot.decode()}

        def recognize(self, screenshot, assist, *, server):
            nonlocal recognition_count
            assert screenshot == b"main"
            recognition_count += 1
            found = candidates if recognition_count == 1 else [
                {**candidate, "anchor": [100, candidate["anchor"][1] + row_shift]}
                for candidate in candidates
            ]
            return {"candidate_count": 2, "servant_name": "Support", "candidates": found}

        def check_append_skills(self, screenshot, candidate, levels, *, server):
            assert screenshot == b"append"
            assert levels == [0, 10, 0, 0, 0]
            checked.append(candidate["anchor"])
            return {"matched": matching and candidate["anchor"][1] == 450, "levels": [None, 10, None, None, None]}

    script_data = SimpleNamespace(get_setting_plan=lambda _name: {
        "server": "CH", "run": {}, "assist": {
            "mode": "仅从者", "all_not_skip": True, "append_skill_levels": [0, 10, 0, 0, 0],
        },
    })
    context = SimpleNamespace(checkpoint=lambda *_a, **_k: None, emit=lambda *_a, **_k: None, sleep=lambda _s: None)
    handler = create_assist_handler(script_data, Device(), Recognizer())
    payload = {"setting_name": "demo", "max_scrolls": 0, "max_refreshes": 0}
    if matching and not row_shift:
        result = handler(context, payload)
        assert result["selected"]["anchor"] == [100, 450]
        assert result["selected"]["checks"]["append_skill_levels"] == [None, 10, None, None, None]
        assert taps[-1] == (370, 390)
    else:
        with pytest.raises(RuntimeError, match="No matching assist"):
            handler(context, payload)
        assert state["view"] == "main"
        assert all(point == (847, 130) for point in taps)
    assert checked == [[100, 200], [100, 450]]


@pytest.mark.parametrize("view", [None, "append"])
def test_assist_handler_stops_when_skill_view_cannot_be_confirmed(view):
    taps = []
    script_data = SimpleNamespace(get_setting_plan=lambda _name: {
        "server": "CH", "run": {}, "assist": {"all_not_skip": True, "append_skill_levels": [0, 10, 0]},
    })
    def tap(*point):
        taps.append(point)
        return SimpleNamespace(to_dict=lambda: {"ok": True})

    device = SimpleNamespace(snapshot=lambda: b"unknown", tap=tap)
    recognizer = SimpleNamespace(
        match_reconnect=lambda *_args: SimpleNamespace(matched=False),
        match_skill_view=lambda *_args: {"view": view} if view else None,
        recognize=lambda *_args, **_kwargs: pytest.fail("recognized unconfirmed view"),
    )
    context = SimpleNamespace(checkpoint=lambda *_a, **_k: None, emit=lambda *_a, **_k: None, sleep=lambda _s: None)
    with pytest.raises(RuntimeError, match="skill view"):
        create_assist_handler(script_data, device, recognizer)(context, {"setting_name": "demo"})
    assert len(taps) == (5 if view else 0)
    assert all(point == (847, 130) for point in taps)
