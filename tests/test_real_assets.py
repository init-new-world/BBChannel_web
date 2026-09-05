from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image, ImageChops

from webapp.services.resources import ResourceService


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _png_bytes(image: Image.Image) -> bytes:
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.mark.parametrize("server", ["CH", "JP", "CNTW"])
@pytest.mark.parametrize("status", [None, "freeze", "bjfy"])
def test_np_status_templates_only_match_the_blocked_np(server, status):
    cv = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    from webapp.services import cards
    from webapp.services.recognition import RecognitionService

    resources = ResourceService(PROJECT_ROOT / "assets", PROJECT_ROOT / "data")
    screenshot = Image.new("RGB", (1280, 720), (18, 24, 32))
    with Image.open(resources.resolve_template("commands_JP/100300/card_servant_1.png")) as source:
        portrait = source.convert("RGBA")
    for slot in range(3):
        screenshot.paste(portrait, (round((483 + 347 * slot) * 2 / 3), 60), portrait)
    if status:
        with Image.open(resources.resolve_template(f"battle/{server}/{status}.png")) as source:
            template = source.convert("RGBA")
        scaled = Image.fromarray(cv.resize(
            np.asarray(template), (round(template.width * 2 / 3), round(template.height * 2 / 3)),
            interpolation=cv.INTER_AREA,
        ))
        screenshot.paste(scaled, (697, 181), scaled)
        screenshot.paste(scaled, (184, 477), scaled)
    report = cards.recognize_card_blocks(RecognitionService(resources), _png_bytes(screenshot), server)
    reason = {"freeze": "immobilized", "bjfy": "sealed"}.get(status)
    assert report == {"nps": {2: reason} if status else {}, "faces": {1: reason} if status else {}}


def test_real_lfs_template_indexes_matches_and_renders_debug_overlay():
    pytest.importorskip("cv2")
    from webapp.services.recognition import RecognitionService

    resources = ResourceService(PROJECT_ROOT / "assets", PROJECT_ROOT / "data")
    template_path = "battle/CH/AP.png"

    page = resources.template_index(prefix="battle/CH", query="AP.png", limit=20)
    assert template_path in [entry["path"] for entry in page["entries"]]

    metadata = resources.template_metadata(template_path)
    assert metadata["format"] == "PNG"
    assert metadata["width"] == 44
    assert metadata["height"] == 33

    with Image.open(resources.resolve_template(template_path)) as source:
        template = source.convert("RGB")
    scaled = template.resize((66, 50), Image.Resampling.BILINEAR)
    screenshot = Image.new("RGB", (280, 180), (19, 27, 37))
    screenshot.paste(scaled, (143, 89))
    screenshot_bytes = _png_bytes(screenshot)

    result, overlay_bytes = RecognitionService(resources).match_template_debug(
        screenshot_bytes,
        template_path,
        threshold=0.9,
        roi=[120, 70, 120, 90],
        scales=[1.0, 1.5],
    )

    overlay = Image.open(BytesIO(overlay_bytes)).convert("RGB")
    assert result.matched is True
    assert result.confidence >= 0.99
    assert result.scale == 1.5
    assert result.top_left == [143, 89]
    assert result.center == [176, 114]
    assert result.size == [66, 50]
    assert result.roi == [120, 70, 120, 90]
    assert overlay.size == screenshot.size
    assert ImageChops.difference(screenshot, overlay).getbbox() is not None


def test_real_command_card_template_matches_with_transparency():
    pytest.importorskip("cv2")
    from webapp.services.recognition import RecognitionService

    resources = ResourceService(PROJECT_ROOT / "assets", PROJECT_ROOT / "data")
    template_path = "commands_CH/100100/card_servant_1.png"
    with Image.open(resources.resolve_template(template_path)) as source:
        template = source.convert("RGBA")
    screenshot = Image.new("RGB", (500, 400), (40, 70, 110))
    screenshot.paste(template, (140, 80), template)

    result = RecognitionService(resources).match_template(
        _png_bytes(screenshot),
        template_path,
        threshold=0.95,
    )

    assert result.matched is True
    assert result.confidence >= 0.98
    assert result.top_left == [140, 80]


def test_real_chocolate_templates_report_storage_limit():
    pytest.importorskip("cv2")
    from webapp.services.chocolate import ChocolateRecognizer
    from webapp.services.recognition import RecognitionService

    resources = ResourceService(PROJECT_ROOT / "assets", PROJECT_ROOT / "data")
    template_path = "chocolate/CH/limit.png"
    with Image.open(resources.resolve_template(template_path)) as source:
        template = source.convert("RGBA")
    screenshot = Image.new("RGB", (1280, 720), (24, 31, 43))
    screenshot.paste(template, (510, 320), template)

    report = ChocolateRecognizer(resources, RecognitionService(resources)).recognize(
        _png_bytes(screenshot),
        "CH",
        threshold=0.95,
    )

    assert report["state"] == "limit"
    assert report["status"] == "blocked"
    assert report["reason"] == "storage_full"
    assert report["matches"][0]["template_path"] == template_path


def test_real_expball_templates_classify_a_storage_grid_slot():
    pytest.importorskip("cv2")
    from webapp.services.expball import ExpBallRecognizer
    from webapp.services.recognition import RecognitionService

    resources = ResourceService(PROJECT_ROOT / "assets", PROJECT_ROOT / "data")
    template_path = "expball/FPgold/4jyz.png"
    with Image.open(resources.resolve_template(template_path)) as source:
        template = source.convert("RGBA")
    screenshot = Image.new("RGB", (1280, 720), (24, 31, 43))
    screenshot.paste(template, (100, 210), template)

    report = ExpBallRecognizer(
        resources,
        RecognitionService(resources),
    ).recognize_storage_grid(
        _png_bytes(screenshot),
        threshold=0.95,
    )

    assert report["recognized_count"] == 1
    assert report["slots"][0]["star"] == 4
    assert report["slots"][0]["confidence"] >= 0.99
    assert all(slot["star"] is None for slot in report["slots"][1:])


@pytest.mark.parametrize("server", ["CH", "JP", "CNTW"])
@pytest.mark.parametrize("status", [None, "freeze", "bjfy"])
def test_real_card_status_templates_distinguish_text_from_portrait_art(server, status):
    cv = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    from webapp.services.cards import CARD_STATUS_ROIS, CommandCardRecognizer
    from webapp.services.recognition import RecognitionService

    resources = ResourceService(PROJECT_ROOT / "assets", PROJECT_ROOT / "data")
    screenshot = Image.new("RGB", (1280, 720), (18, 24, 32))
    with Image.open(resources.resolve_template("commands_JP/100300/card_servant_1.png")) as source:
        portrait = source.convert("RGBA")

    def paste_scaled(path, position):
        with Image.open(resources.resolve_template(path)) as source:
            template = source.convert("RGBA")
        scaled = Image.fromarray(cv.resize(
            np.asarray(template), (round(template.width * 2 / 3), round(template.height * 2 / 3)),
            interpolation=cv.INTER_AREA,
        ))
        screenshot.paste(scaled, position, scaled)

    for slot, color in enumerate(("Buster", "Arts", "Quick", "Arts", "Buster")):
        screenshot.paste(portrait, (slot * 256, 400), portrait)
        paste_scaled(f"battle/{server}/{color}.png", (slot * 256 + 20, 610))
    if status:
        x, y, _width, _height = CARD_STATUS_ROIS[2]
        paste_scaled(f"battle/{server}/{status}.png", (x + 4, y + 4))
    servants = [{"active": True, "sn": "100300"}] if server == "JP" else []
    result = CommandCardRecognizer(resources, RecognitionService(resources)).recognize(
        _png_bytes(screenshot), server, servants, threshold=0.8,
    )
    reason = {"freeze": "immobilized", "bjfy": "sealed"}.get(status)
    assert [card["blocked_reason"] for card in result["cards"]] == [None, None, reason, None, None]
    if server == "JP":
        assert result["complete"] is True
        assert result["recognized_count"] == (4 if status else 5)
        assert [card["code"] for card in result["cards"]] == ["1B", "1A", None if status else "1Q", "1A", "1B"]
        if status is None:
            from webapp.automation.battle import _execute_strategy_step, _matches_hakuno_needs

            assert _matches_hakuno_needs(result["cards"], [["1B"]]) is True
            strategy = {"card1": {"type": 0, "cards": [1]}, "card2": {"type": 2}, "card3": {"type": 2}}
            for avoid_chain in (False, True):
                taps = []

                def tap(x, y):
                    taps.append((x, y))
                    return SimpleNamespace(to_dict=lambda: {"ok": True})

                count = _execute_strategy_step(
                    SimpleNamespace(emit=lambda *_args, **_kwargs: None, sleep=lambda _seconds: None),
                    SimpleNamespace(tap=tap), SimpleNamespace(recognize=lambda *_args, **_kwargs: result),
                    b"classified-frame", "JP", servants,
                    {"strategies": [strategy], "avoid_chain": avoid_chain, "preselected_nps": [1]},
                    0.8, 0,
                )
                assert count == 3
                assert taps == [(500, 110), (150, 500), (375, 500)]
