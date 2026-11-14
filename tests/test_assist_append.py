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
@pytest.mark.parametrize("substitute", [False, True])
def test_assist_handler_filters_append_levels_and_restores_main_view(initial_view, matching, row_shift, substitute):
    state = {"view": initial_view}
    taps = []
    checked = []
    recognition_count = 0
    candidates = [{"anchor": [100, y], "scale": 1.0, "checks": {}} for y in (200, 450)]

    class Device:
        def snapshot(self):
            return ("main-restored" if state["view"] == "main" and checked else state["view"]).encode()

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
            return {"view": screenshot.decode().split("-")[0]}

        def candidate_identity(self, screenshot, candidate):
            if substitute and screenshot == b"main-restored" and candidate["anchor"][1] == 450:
                return "replacement-player"
            return f"player-{candidate['anchor'][1]}"

        def recognize(self, screenshot, assist, *, server):
            nonlocal recognition_count
            assert screenshot in (b"main", b"main-restored")
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
    if matching and not row_shift and not substitute:
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


def test_append_filter_refreshes_a_positively_recognized_empty_list():
    refresh_checks = []
    script_data = SimpleNamespace(get_setting_plan=lambda _name: {
        "server": "CH", "run": {}, "assist": {"all_not_skip": True, "append_skill_levels": [0, 10, 0]},
    })
    device = SimpleNamespace(snapshot=lambda: b"empty", tap=lambda *_args: pytest.fail("unexpected tap"))
    def check_refresh(*_args):
        refresh_checks.append(True)
        return SimpleNamespace(matched=False)
    recognizer = SimpleNamespace(
        match_reconnect=lambda *_args: SimpleNamespace(matched=False),
        match_no_assist=lambda *_args: SimpleNamespace(matched=True),
        match_skill_view=lambda *_args: pytest.fail("empty list has no skill view"),
        recognize=lambda *_args, **_kwargs: pytest.fail("empty list has no candidates"),
        match_refresh_button=check_refresh,
    )
    context = SimpleNamespace(checkpoint=lambda *_a, **_k: None, emit=lambda *_a, **_k: None, sleep=lambda _s: None)
    with pytest.raises(RuntimeError, match="refresh button"):
        create_assist_handler(script_data, device, recognizer)(context, {"setting_name": "demo", "max_refreshes": 1})
    assert refresh_checks == [True]


def test_support_identity_excludes_skill_digits_but_includes_player_name(append_recognizer):
    recognizer, _templates = append_recognizer
    main = Image.new("RGB", (1280, 720), (20, 25, 35))
    ImageDraw.Draw(main).text((1080, 150), "Player B", fill="white")
    append = main.copy()
    ImageDraw.Draw(append).rectangle((820, 240, 1020, 300), fill="cyan")
    changed_player = append.copy()
    ImageDraw.Draw(changed_player).rectangle((1080, 150, 1160, 170), fill="red")
    candidate = {"anchor": [100, 200]}
    original = recognizer.candidate_identity(_png(main), candidate)
    assert recognizer.candidate_identity(_png(append), candidate) == original
    assert recognizer.candidate_identity(_png(changed_player), candidate) != original


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


def test_match_skill_view_ignores_antialiased_rgba_alpha_mask_false_positives(tmp_path):
    pytest.importorskip("cv2")
    assets = tmp_path / "assets"
    directory = assets / "battle" / "CH"
    directory.mkdir(parents=True)

    main_tpl = Image.new("RGBA", (90, 24), (240, 220, 50, 255))
    draw_main = ImageDraw.Draw(main_tpl)
    draw_main.text((8, 5), "main", fill=(0, 0, 0, 255))
    main_tpl.putpixel((0, 0), (240, 220, 50, 222))
    main_tpl.save(directory / "main_skill.png")

    append_tpl = Image.new("RGBA", (90, 24), (40, 180, 220, 255))
    draw_app = ImageDraw.Draw(append_tpl)
    draw_app.text((8, 5), "append", fill=(0, 0, 0, 255))
    append_tpl.putpixel((0, 0), (40, 180, 220, 222))
    append_tpl.save(directory / "append_skill.png")

    screen = Image.new("RGB", (1280, 720), (40, 60, 80))
    # Bright divider stripe below the main header that triggers high TM_CCORR_NORMED if alpha mask is enabled.
    ImageDraw.Draw(screen).rectangle((820, 520, 950, 540), fill=(210, 200, 175))
    screen.paste(main_tpl.resize((60, 16), Image.Resampling.LANCZOS).convert("RGB"), (830, 320))

    resources = ResourceService(assets, tmp_path / "data")
    recognizer = AssistRecognizer(resources, RecognitionService(resources))
    marker = recognizer.match_skill_view(_png(screen), "CH")
    assert marker is not None
    assert marker["view"] == "main"
    assert recognizer.match_skill_view(_png(screen), "CH", anchor=[130, 500]) is None


def test_same_candidate_row_tolerates_right_strip_animation_and_rejects_changes(append_recognizer):
    recognizer, _templates = append_recognizer
    base = Image.new("RGB", (1280, 720), (20, 25, 35))
    draw = ImageDraw.Draw(base)
    draw.rectangle((40, 120, 190, 270), fill=(90, 140, 200))
    draw.text((400, 140), "Master A", fill="white")
    draw.rectangle((1080, 150, 1180, 175), fill="gold")

    animated = base.copy()
    anim_draw = ImageDraw.Draw(animated)
    anim_draw.rectangle((820, 220, 1020, 300), fill="cyan")
    # Simulated animated support rays / FP shimmer in the right strip + faint edge pixel jitter.
    anim_draw.rectangle((1090, 225, 1260, 305), fill=(240, 250, 255))
    animated.putpixel((400, 140), (253, 253, 253))

    replaced_player = base.copy()
    ImageDraw.Draw(replaced_player).rectangle((400, 130, 620, 185), fill="red")

    cand = {"anchor": [100, 200]}
    shifted = {"anchor": [100, 235]}
    assert recognizer.same_candidate_row(_png(base), cand, _png(animated), cand)
    assert not recognizer.same_candidate_row(_png(base), cand, _png(replaced_player), cand)
    assert not recognizer.same_candidate_row(_png(base), cand, _png(base), shifted)
