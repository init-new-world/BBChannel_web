from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from webapp.core.models import MatchResult
from webapp.services.recognition import RecognitionService
from webapp.services.resources import ResourceService
from webapp.services.quest import QuestRecognizer


def _match(
    template_path: str,
    center: list[int],
    *,
    matched: bool = True,
    confidence: float = 0.95,
) -> MatchResult:
    return MatchResult(
        template_path=template_path,
        matched=matched,
        confidence=confidence,
        threshold=0.8,
        top_left=[center[0] - 20, center[1] - 10],
        size=[40, 20],
        center=center,
        scale=2 / 3,
    )


class _Recognition:
    def __init__(self) -> None:
        self.all_calls: list[dict] = []
        self.clear_calls: list[dict] = []

    def match_template_all(self, _screenshot, template_path, **options):
        self.all_calls.append({"template_path": template_path, **options})
        if template_path.endswith("freeQuest.png"):
            return [
                _match(template_path, [700, 360], confidence=0.91),
                _match(template_path, [700, 180], confidence=0.94),
            ]
        return [_match(template_path, [700, 540], confidence=0.93)]

    def match_template(self, _screenshot, template_path, **options):
        self.clear_calls.append({"template_path": template_path, **options})
        center_y = options["roi"][1]
        return _match(
            template_path,
            [700, center_y],
            matched=center_y < 300,
        )


def test_free_quest_recognizer_selects_first_uncleared_visible_entry():
    recognition = _Recognition()

    result = QuestRecognizer(recognition).recognize_free_quests(
        b"screen",
        "ch",
    )

    assert result["server"] == "CH"
    assert result["candidate_count"] == 3
    assert [candidate["center"] for candidate in result["candidates"]] == [
        [700, 180],
        [700, 360],
        [700, 540],
    ]
    assert [candidate["cleared"] for candidate in result["candidates"]] == [
        True,
        False,
        False,
    ]
    assert result["selected"] == result["candidates"][1]


def test_free_quest_recognizer_uses_original_list_and_clear_regions():
    recognition = _Recognition()

    QuestRecognizer(recognition).recognize_free_quests(b"screen", "JP")

    assert recognition.all_calls == [
        {
            "template_path": "battle/Free/JP/freeQuest.png",
            "threshold": 0.8,
            "roi": (600, 0, 200, 720),
            "scales": (1.0, 0.75, 2 / 3, 0.5),
            "max_results": 20,
        },
        {
            "template_path": "battle/Free/JP/freeQuest1.png",
            "threshold": 0.8,
            "roi": (600, 0, 200, 720),
            "scales": (1.0, 0.75, 2 / 3, 0.5),
            "max_results": 20,
        },
    ]
    assert [call["roi"] for call in recognition.clear_calls] == [
        (647, 230, 107, 34),
        (647, 410, 107, 34),
        (647, 590, 107, 34),
    ]
    assert all(
        call["template_path"] == "battle/Free/JP/clear.png"
        and call["threshold"] == 0.8
        and call["scales"] == (2 / 3,)
        and call["template_size"] == (160, 50)
        for call in recognition.clear_calls
    )


def test_free_quest_recognizer_returns_no_selection_when_every_entry_is_clear():
    recognition = _Recognition()

    def clear_match(_screenshot, template_path, **options):
        return _match(template_path, [700, options["roi"][1]], matched=True)

    recognition.match_template = clear_match

    result = QuestRecognizer(recognition).recognize_free_quests(b"screen", "CNTW")

    assert result["candidate_count"] == 3
    assert result["selected"] is None


def test_free_quest_recognizer_matches_clear_badge_with_real_opencv(tmp_path: Path):
    pytest.importorskip("cv2")
    assets = tmp_path / "assets"
    data = tmp_path / "data"
    free_assets = assets / "battle" / "Free" / "CH"
    free_assets.mkdir(parents=True)
    data.mkdir()

    quest = Image.new("RGB", (90, 60), (25, 40, 70))
    quest_draw = ImageDraw.Draw(quest)
    quest_draw.rectangle((3, 3, 86, 56), outline=(230, 190, 55), width=3)
    quest_draw.line((8, 48, 78, 10), fill=(40, 220, 180), width=4)
    alternate = Image.new("RGB", (90, 60), (75, 25, 40))
    alternate_draw = ImageDraw.Draw(alternate)
    alternate_draw.ellipse((15, 10, 70, 50), outline=(220, 220, 220), width=4)
    clear = Image.new("RGB", (160, 50), (35, 60, 35))
    clear_draw = ImageDraw.Draw(clear)
    clear_draw.rectangle((2, 2, 157, 47), outline=(220, 235, 90), width=3)
    clear_draw.line((20, 25, 140, 25), fill=(245, 245, 245), width=4)
    quest.save(free_assets / "freeQuest.png")
    alternate.save(free_assets / "freeQuest1.png")
    clear.save(free_assets / "clear.png")

    screenshot = Image.new("RGB", (1280, 720), (12, 18, 24))
    screenshot.paste(quest, (650, 150))
    center = [695, 180]
    clear_badge = clear.resize((107, 33))
    screenshot.paste(clear_badge, (642, 230))
    encoded = BytesIO()
    screenshot.save(encoded, format="PNG")
    resources = ResourceService(assets, data)

    result = QuestRecognizer(
        RecognitionService(resources),
    ).recognize_free_quests(encoded.getvalue(), "CH", threshold=0.99)

    assert result["candidate_count"] == 1
    assert result["candidates"][0]["center"] == center
    assert result["candidates"][0]["cleared"] is True
    assert result["selected"] is None


def test_free_map_recognizer_filters_unsafe_red_dots_and_offsets_touch_point():
    class MapRecognition:
        def __init__(self) -> None:
            self.calls = []

        def match_template_all(self, _screenshot, template_path, **options):
            self.calls.append({"template_path": template_path, **options})
            return [
                _match(template_path, [400, 300], confidence=0.93),
                _match(template_path, [180, 520], confidence=0.99),
                _match(template_path, [600, 570], confidence=0.98),
            ]

    recognition = MapRecognition()

    result = QuestRecognizer(recognition).recognize_free_map(b"screen")

    assert recognition.calls == [
        {
            "template_path": "battle/Free/reddot.png",
            "threshold": 0.8,
            "scales": (1.0, 0.75, 2 / 3, 0.5),
            "mask_path": "battle/Free/reddotMask.png",
            "max_results": 50,
        }
    ]
    assert result["candidate_count"] == 1
    assert result["candidates"][0]["center"] == [400, 300]
    assert result["candidates"][0]["touch"] == [373, 327]
    assert result["selected"] == result["candidates"][0]


def test_free_quest_recognizer_keeps_bottom_candidate_when_clear_badge_is_offscreen():
    class BottomRecognition:
        def match_template_all(self, _screenshot, template_path, **_options):
            if template_path.endswith("freeQuest.png"):
                return [_match(template_path, [700, 690])]
            return []

        def match_template(self, *_args, **_kwargs):
            raise AssertionError("offscreen clear ROI must not be matched")

    result = QuestRecognizer(BottomRecognition()).recognize_free_quests(
        b"screen",
        "CH",
    )

    assert result["candidate_count"] == 1
    assert result["candidates"][0]["center"] == [700, 690]
    assert result["candidates"][0]["cleared"] is False
    assert result["candidates"][0]["clear_visible"] is False
    assert result["candidates"][0]["clear_confidence"] is None
    assert result["selected"] == result["candidates"][0]
