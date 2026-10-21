from io import BytesIO
from types import SimpleNamespace

import pytest
from PIL import Image, ImageDraw

from webapp.automation.assist import create_assist_handler
from webapp.core.errors import AppError, ErrorCode
from webapp.services.assist import AssistRecognizer
from webapp.services.recognition import RecognitionService
from webapp.services.resources import ResourceService


@pytest.mark.parametrize("friend_only,friend_present,max_scrolls,refresh_target,expected_scrolls", [
    (True, False, 6, 1, 2),
    (True, False, 6, 2, 4),
    (True, True, 6, 1, 6),
    (False, False, 6, 1, 6),
    (True, None, 6, 1, 6),
    (True, False, 1, 1, 1),
])
def test_assist_friend_only_refreshes_after_two_scrolls_without_friends(
    friend_only, friend_present, max_scrolls, refresh_target, expected_scrolls,
):
    taps = []
    scrolls = []
    friend_checks = []
    refreshes = 0
    confirmation_open = False

    class Device:
        def snapshot(self):
            if confirmation_open:
                return b"confirmation"
            return b"candidate" if refreshes >= refresh_target else b"list"

        def tap(self, x, y):
            nonlocal confirmation_open, refreshes
            taps.append((x, y))
            if (x, y) == (1130, 65):
                confirmation_open = True
            elif (x, y) == (615, 410):
                confirmation_open = False
                refreshes += 1
            return SimpleNamespace(to_dict=lambda: {"ok": True})

        def swipe(self, *args):
            scrolls.append(args)
            return SimpleNamespace(to_dict=lambda: {"ok": True})

    def match(matched=False, center=(0, 0)):
        return SimpleNamespace(matched=matched, center=center, size=(20, 20))

    class Recognizer:
        def match_reconnect(self, *_args):
            return match()

        def match_not_available(self, *_args):
            return match()

        def match_no_assist(self, *_args):
            return match()

        def match_scrollbar(self, *_args):
            return match()

        def match_friend_marker(self, screenshot, server):
            assert screenshot == b"list" and server == "CH"
            friend_checks.append((refreshes, len(scrolls)))
            if friend_present is None:
                raise AppError(ErrorCode.TEMPLATE_NOT_FOUND, "Missing friend marker")
            return match(friend_present)

        def match_refresh_button(self, screenshot, _server):
            return match(screenshot == b"list", (1130, 65))

        def match_refresh_confirmation(self, screenshot, _server):
            return match(screenshot == b"confirmation", (615, 410))

        def recognize(self, screenshot, *_args, **_options):
            candidates = [{"anchor": [70, 225], "scale": 1, "checks": {}}] if screenshot == b"candidate" else []
            return {"servant_name": "Support", "candidate_count": len(candidates), "candidates": candidates}

    script_data = SimpleNamespace(get_setting_plan=lambda _: {
        "server": "CH", "assist": {"mode": "从者礼装", "friend_only": friend_only},
        "run": {"random_time": 0, "random_touch": False},
    })
    context = SimpleNamespace(checkpoint=lambda *_args, **_options: None, sleep=lambda _: None,
                              emit=lambda *_args, **_options: None)

    result = create_assist_handler(script_data, Device(), Recognizer())(context, {
        "setting_name": "demo", "max_scrolls": max_scrolls, "max_refreshes": refresh_target,
        "tap_wait_seconds": 0, "scroll_wait_seconds": 0, "refresh_wait_seconds": 0,
    })

    assert len(scrolls) == expected_scrolls
    assert result["refreshes"] == refresh_target
    expected_hits = refresh_target if friend_only and friend_present is False and max_scrolls > 2 else 0
    assert result["friend_boundary_hits"] == expected_hits
    assert taps == [(1130, 65), (615, 410)] * refresh_target + [(340, 165)]
    assert all(total >= 2 * (cycle + 1) for cycle, total in friend_checks)


@pytest.mark.parametrize("server", ["CH", "CNTW", "JP"])
@pytest.mark.parametrize("marker_x", [1100, 500])
def test_assist_friend_marker_uses_original_right_hand_region(tmp_path, server, marker_x):
    cv = pytest.importorskip("cv2")
    numpy = pytest.importorskip("numpy")
    assets = tmp_path / "assets"
    battle = assets / "battle" / server
    battle.mkdir(parents=True)
    marker = Image.new("RGB", (73, 62), (35, 85, 165))
    draw = ImageDraw.Draw(marker)
    draw.rectangle((3, 4, 68, 57), outline="white", width=4)
    draw.line((10, 40, 55, 15), fill=(235, 205, 50), width=5)
    marker.save(battle / "friend.png")
    scaled = Image.fromarray(cv.resize(numpy.array(marker), (49, 41), interpolation=cv.INTER_AREA))
    screen = Image.new("RGB", (1280, 720), (20, 30, 45))
    screen.paste(scaled, (marker_x, 300))
    buffer = BytesIO()
    screen.save(buffer, format="PNG")
    resources = ResourceService(assets, tmp_path / "data")

    match = AssistRecognizer(resources, RecognitionService(resources)).match_friend_marker(buffer.getvalue(), server)

    assert match.matched == (marker_x == 1100)
    assert match.roi == [1087, 157, 120, 563]
