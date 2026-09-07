from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from webapp.services.cards import CommandCardRecognizer
from webapp.services.recognition import RecognitionService
from webapp.services.resources import ResourceService


@pytest.fixture
def special_key_recognizer(tmp_path: Path):
    pytest.importorskip("cv2")
    assets = tmp_path / "assets"
    data = tmp_path / "data"
    data.mkdir()
    server = assets / "battle" / "CH"
    server.mkdir(parents=True)
    for name in ("Arts", "Buster", "Quick", "freeze", "bjfy"):
        Image.new("RGB", (8, 8), (40, 90, 130)).save(server / f"{name}.png")
    stars = assets / "battle" / "public" / "starNum"
    stars.mkdir(parents=True)
    for number in range(10):
        Image.new("L", (8, 8), 100).save(stars / f"n{number}.png")
        Image.new("L", (8, 8), 255).save(stars / f"n{number}mask.png")
    (assets / "special_keys").mkdir()
    resources = ResourceService(assets, data)
    return CommandCardRecognizer(resources, RecognitionService(resources)), assets


def _screenshot_bytes(image: Image.Image) -> bytes:
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.mark.parametrize("source_size", [(960, 540), (1280, 720), (1920, 1080), (2400, 1080), (1280, 960)])
def test_special_keys_use_source_scale_and_card_local_search_region(special_key_recognizer, source_size):
    cv = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    recognizer, assets = special_key_recognizer
    source_scale = min(source_size[0] / 1920, source_size[1] / 1080)
    size = round(36 * source_scale)
    template = np.random.default_rng(42).integers(20, 235, (size, size, 3), dtype=np.uint8)
    Image.fromarray(template).save(assets / "special_keys" / "key.png")
    interpolation = cv.INTER_AREA if size > 24 else cv.INTER_LINEAR
    displayed = Image.fromarray(cv.resize(template, (24, 24), interpolation=interpolation))
    screenshot = Image.new("RGB", (1280, 720), (18, 24, 32))
    # Same motif in the wrong part of a card must not satisfy the localized key.
    locations = [(60 + 30, 530 + 90), (444 + 150, 530 + 90),
                 (826 + 30, 530 + 130), (1212 + 30, 530 + 175), (1601 + 30, 530 + 90)]
    for x, y in locations:
        screenshot.paste(displayed, (round(x * 2 / 3), round(y * 2 / 3)))
    result = recognizer.recognize(
        _screenshot_bytes(screenshot), "CH", [],
        special_keys=[{
            "code": "S0", "template_path": "special_keys/key.png", "threshold": 0.99,
            "source_width": source_size[0], "source_height": source_size[1],
            "left": round(30 * source_scale), "right": round(66 * source_scale),
            "top": round(90 * source_scale), "bottom": round(126 * source_scale),
        }],
    )
    assert [card["special_keys"] for card in result["cards"]] == [["S0"], [], ["S0"], [], ["S0"]]


@pytest.mark.parametrize("metadata", [
    {"source_width": 1280},
    {"source_width": 0, "source_height": 720, "left": 0, "right": 24, "top": 0, "bottom": 24},
    {"source_width": 1280, "source_height": 720, "left": 24, "right": 0, "top": 0, "bottom": 24},
    {"source_width": 1280, "source_height": 720, "left": True, "right": 24, "top": 0, "bottom": 24},
])
def test_special_key_partial_or_invalid_geometry_is_rejected(special_key_recognizer, metadata):
    recognizer, _assets = special_key_recognizer
    with pytest.raises(ValueError, match="Special key.*metadata"):
        recognizer.recognize(
            _screenshot_bytes(Image.new("RGB", (1280, 720))), "CH", [],
            special_keys=[{"code": "S0", "template_path": "special_keys/missing.png", **metadata}],
        )


@pytest.mark.parametrize("bounds", [(-100, -64, 90, 126), (0, 400, 0, 400)])
def test_special_key_outside_card_or_larger_than_card_is_not_matched(special_key_recognizer, bounds):
    recognizer, _assets = special_key_recognizer
    left, right, top, bottom = bounds
    result = recognizer.recognize(
        _screenshot_bytes(Image.new("RGB", (1280, 720))), "CH", [],
        special_keys=[{
            "code": "S0", "template_path": "special_keys/unused.png", "threshold": 0.99,
            "source_width": 1920, "source_height": 1080,
            "left": left, "right": right, "top": top, "bottom": bottom,
        }],
    )
    assert all(card["special_keys"] == [] for card in result["cards"])


@pytest.mark.parametrize("source_slot", [1, 2, 3, 4, 5])
def test_created_command_tag_resolves_and_matches_each_card_slot(special_key_recognizer, source_slot):
    np = pytest.importorskip("numpy")
    from webapp.services.command_tags import CommandTagService
    from webapp.services.script_data import ScriptDataService

    recognizer, assets = special_key_recognizer
    resources = ResourceService(assets, assets.parent / "data")
    tags = CommandTagService(resources)
    screen = Image.new("RGB", (1280, 720), (18, 24, 32))
    motif = Image.fromarray(np.random.default_rng(73).integers(20, 235, (24, 24, 3), dtype=np.uint8))
    candidates = tags.candidates()
    for candidate in candidates:
        x, y = candidate["anchor"]
        screen.paste(motif, (x + 20, y + 60))
    x, y = candidates[source_slot - 1]["anchor"]
    tag = tags.build_card(
        label="Runtime", screenshot=_screenshot_bytes(screen), slot=source_slot,
        bounds=[x + 20, y + 60, x + 44, y + 84], threshold=0.99,
    )
    keys = ScriptDataService._plan_special_keys({"specialKeys": [tag["template_path"]]})
    assert resources.resolve_template(keys[0]["template_path"]).is_file()
    result = recognizer.recognize(_screenshot_bytes(screen), "CH", [], special_keys=keys)
    assert [card["special_keys"] for card in result["cards"]] == [["S0"]] * 5


def test_full_width_command_tag_remains_portable_between_slots(special_key_recognizer):
    np = pytest.importorskip("numpy")
    from webapp.services.command_tags import CommandTagService
    from webapp.services.script_data import ScriptDataService

    recognizer, assets = special_key_recognizer
    tags = CommandTagService(ResourceService(assets, assets.parent / "data"))
    candidates = tags.candidates()
    screen = Image.new("RGB", (1280, 720), (18, 24, 32))
    motif = Image.fromarray(np.random.default_rng(85).integers(20, 235, (260, 193, 3), dtype=np.uint8))
    for candidate in candidates:
        screen.paste(motif, tuple(candidate["anchor"]))
    x, y, width, height = candidates[-1]["bounds"]
    tag = tags.build_card(
        label="FullWidth", screenshot=_screenshot_bytes(screen), slot=5,
        bounds=[x, y, x + width, y + height], threshold=0.99,
    )
    keys = ScriptDataService._plan_special_keys({"specialKeys": [tag["template_path"]]})
    result = recognizer.recognize(_screenshot_bytes(screen), "CH", [], special_keys=keys)
    assert [card["special_keys"] for card in result["cards"]] == [["S0"]] * 5
