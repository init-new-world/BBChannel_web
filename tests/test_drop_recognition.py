from io import BytesIO
from pathlib import Path
from random import Random

import pytest
from PIL import Image, ImageDraw

from tests.test_completion_job import _pattern, _run_completion
from webapp.runtime import JobDatabase, JobStatus
from webapp.services.recognition import RecognitionService
from webapp.services.resources import ResourceService
from webapp.core.models import MatchResult

pytest.importorskip("cv2")


def _png(image):
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _drop_art(size=(176, 193), *, low_contrast_center=False):
    random = Random(934)
    image = Image.new("RGB", size)
    draw = ImageDraw.Draw(image)
    for y in range(0, size[1], 8):
        for x in range(0, size[0], 8):
            color = tuple(random.randrange(10, 240) for _ in range(3))
            draw.rectangle((x, y, x + 7, y + 7), fill=color)
    if low_contrast_center:
        left, top, right, bottom = _crop(size)
        for y in range(top, bottom, 8):
            for x in range(left, right, 8):
                gray = random.randrange(56, 65)
                draw.rectangle((x, y, min(x + 7, right - 1), min(y + 7, bottom - 1)), fill=(gray, gray, gray))
    return image


def _crop(size):
    width, height = size
    return width // 4, height // 4, 3 * width // 4, 3 * height // 4


def test_completion_rejects_high_full_image_confidence_with_wrong_center(tmp_path):
    source = _drop_art(low_contrast_center=True)
    wrong = source.copy()
    ImageDraw.Draw(wrong).rectangle(_crop(source.size), fill=(60, 60, 60))
    frame = Image.new("RGB", (1280, 720), (18, 24, 32))
    frame.paste(wrong.resize((117, 129), Image.Resampling.BILINEAR), (300, 250))
    frame.paste(_pattern((120, 50), (35, 120, 170)), (900, 600))
    result = _run_completion(
        tmp_path, [(frame, None)], config={"dropStopNum": 1, "dropImage": "drop/item.png"},
        drop_template=source,
    )
    recognition = RecognitionService(ResourceService(tmp_path / "assets", tmp_path / "data"))
    initial = recognition.match_template_all(_png(frame), "drop/item.png", threshold=0.85, scales=(2 / 3,))
    assert any(match.top_left == [300, 250] for match in initial)
    assert result.status == JobStatus.SUCCEEDED
    assert result.result["complete"] is True
    assert result.result["drop_count"] == 0
    events = JobDatabase(tmp_path / "runtime.db").list_events(result.job_id)
    report = next(event.data for event in events if event.message == "Configured battle drops counted.")
    assert report["candidate_drop_count"] >= 1
    assert report["verified_drop_count"] == 0
    assert report["center_rejected_count"] + report["offset_rejected_count"] == report["candidate_drop_count"]


def _recognizer(tmp_path, size=(176, 193), source=None):
    from webapp.services.drop_recognition import DropRecognizer

    assets = tmp_path / "assets" / "drop"
    assets.mkdir(parents=True)
    source = source if source is not None else _drop_art(size)
    source.save(assets / "item.png")
    resources = ResourceService(tmp_path / "assets", tmp_path / "data")
    recognition = RecognitionService(resources)
    return source, recognition, DropRecognizer(resources, recognition, "drop/item.png")


@pytest.mark.parametrize("source_size", [(176, 193), (352, 386), (177, 193)])
@pytest.mark.parametrize("screen_size", [(1280, 720), (1920, 1080), (1400, 720)])
def test_drop_geometry_uses_original_resolution_formula(tmp_path, monkeypatch, source_size, screen_size):
    _source, recognition, drops = _recognizer(tmp_path, source_size)
    calls = []

    def full_match(_screen, _path, **options):
        calls.append(options)
        return []

    monkeypatch.setattr(recognition, "match_template_all", full_match)
    report = drops.recognize(_png(Image.new("RGB", screen_size)))
    image_scale = (source_size[0] / 176 + source_size[1] / 193) / 2
    expected = min(screen_size[0] / int(1920 * image_scale), screen_size[1] / int(1080 * image_scale))
    assert calls[0]["scales"] == pytest.approx((expected,))
    assert calls[0]["threshold"] == 0.65
    assert calls[0]["grayscale"] is False
    assert calls[0]["use_alpha_mask"] is False
    assert calls[0]["max_results"] == 100
    assert report["matches"] == []
    assert report["candidate_count"] == 0


@pytest.mark.parametrize("screen_size", [(1280, 720), (1920, 1080), (2560, 1440)])
@pytest.mark.parametrize("source_size", [(176, 193), (352, 386), (177, 193)])
def test_drop_recognition_accepts_correct_center_at_each_resolution(tmp_path, screen_size, source_size):
    cv = pytest.importorskip("cv2")
    numpy = pytest.importorskip("numpy")
    source, _recognition, drops = _recognizer(tmp_path, source_size)
    image_scale = (source_size[0] / 176 + source_size[1] / 193) / 2
    scale = min(screen_size[0] / int(1920 * image_scale), screen_size[1] / int(1080 * image_scale))
    size = (round(source_size[0] * scale), round(source_size[1] * scale))
    pixels = cv.resize(numpy.array(source), size, interpolation=cv.INTER_AREA if scale < 1 else cv.INTER_LINEAR)
    frame = Image.new("RGB", screen_size, (18, 24, 32))
    frame.paste(Image.fromarray(pixels), (100, 120))
    report = drops.recognize(_png(frame))
    assert any(result.top_left == [100, 120] for result in report["matches"])


@pytest.mark.parametrize("screen_size", [(1280, 720), (1920, 1080), (2560, 1440)])
@pytest.mark.parametrize("has_drop", [False, True])
def test_bundled_drop_art_only_counts_verified_items(screen_size, has_drop):
    cv = pytest.importorskip("cv2")
    numpy = pytest.importorskip("numpy")
    from webapp.services.drop_recognition import DropRecognizer

    root = Path(__file__).resolve().parents[1]
    resources = ResourceService(root / "assets", root / "data")
    path = "drop/December23rd.png"
    with Image.open(resources.resolve_template(path)) as image:
        source = image.convert("RGB")
    image_scale = (source.width / 176 + source.height / 193) / 2
    scale = min(screen_size[0] / int(1920 * image_scale), screen_size[1] / int(1080 * image_scale))
    size = (round(source.width * scale), round(source.height * scale))
    pixels = cv.resize(numpy.array(source), size, interpolation=cv.INTER_AREA if scale < 1 else cv.INTER_LINEAR)
    frame = Image.new("RGB", screen_size, (18, 24, 32))
    if has_drop:
        frame.paste(Image.fromarray(pixels), (100, 120))
    report = DropRecognizer(resources, RecognitionService(resources), path).recognize(_png(frame))
    assert len(report["matches"]) == int(has_drop)
    if has_drop:
        assert report["matches"][0].top_left == [100, 120]
    assert (len(report["matches"]) + report["center_rejected_count"] + report["offset_rejected_count"]
            == report["candidate_count"])


@pytest.mark.parametrize("size,offset,accepted", [
    ((100, 100), (5, 2), True), ((100, 100), (5, 3), False),
    ((176, 193), (7, 0.5), True), ((176, 193), (8, 0.5), False),
    ((352, 386), (5, 5), True), ((352, 386), (5, 6), False),
])
def test_drop_center_offset_uses_squared_original_tolerance(tmp_path, monkeypatch, size, offset, accepted):
    _source, recognition, drops = _recognizer(tmp_path)
    candidate = MatchResult("drop/item.png", True, 0.9, 0.65, [101, 203], list(size), [0, 0])
    monkeypatch.setattr(recognition, "match_template_all", lambda *args, **kwargs: [candidate])
    captured = []

    def centers(_screen, options):
        captured.extend(options)
        # findBest rounds a crop-local center before comparing to the full candidate.
        point = (size[0] / 2 + offset[0], size[1] / 2 + offset[1])
        return [MatchResult("drop/item.png", True, 0.8, 0.65,
                            [101 + int(point[0]) - 10, 203 + int(point[1]) - 10], [20, 20], [0, 0])]

    monkeypatch.setattr(recognition, "match_templates", centers)
    report = drops.recognize(_png(Image.new("RGB", (1280, 720))))
    assert bool(report["matches"]) is accepted
    assert report["offset_rejected_count"] == (0 if accepted else 1)
    assert captured[0]["grayscale"] is True
    assert captured[0]["use_alpha_mask"] is False
    assert captured[0]["template_crop"] == (44, 48, 132, 144)
    assert captured[0]["roi"] == [101, 203, *size]
    assert captured[0]["scales"] == pytest.approx((min(size[0] / 176, size[1] / 193),))


def test_drop_centers_are_batched_and_cancellation_can_interrupt_before_verification(tmp_path, monkeypatch):
    _source, recognition, drops = _recognizer(tmp_path)
    candidate = MatchResult("drop/item.png", True, 0.9, 0.65, [0, 0], [176, 193], [88, 96])
    monkeypatch.setattr(recognition, "match_template_all", lambda *args, **kwargs: [candidate] * 35)
    sizes = []

    def centers(_screen, options):
        sizes.append(len(options))
        return [MatchResult("drop/item.png", False, 0.2, 0.65, [44, 48], [88, 96], [88, 96])] * len(options)

    monkeypatch.setattr(recognition, "match_templates", centers)
    report = drops.recognize(_png(Image.new("RGB", (1280, 720))))
    assert sizes == [16, 16, 3]
    assert report["center_rejected_count"] == 35
    assert not report["matches"]
    checks = []

    def cancel():
        checks.append(1)
        if len(checks) == 2:
            raise RuntimeError("cancelled")

    sizes.clear()
    with pytest.raises(RuntimeError, match="cancelled"):
        drops.recognize(_png(Image.new("RGB", (1280, 720))), check_cancelled=cancel)
    assert not sizes


def test_ambiguous_diagonal_center_is_rejected_even_with_high_correlation(tmp_path):
    source = _pattern((176, 193), (165, 105, 45))
    _source, _recognition, drops = _recognizer(tmp_path, source=source)
    frame = Image.new("RGB", (1280, 720), (18, 24, 32))
    frame.paste(source.resize((117, 129), Image.Resampling.BILINEAR), (300, 250))
    report = drops.recognize(_png(frame))
    assert report["candidate_count"] == 1
    assert report["center_rejected_count"] == 0
    assert report["offset_rejected_count"] == 1
    assert not report["matches"]


def test_disabled_drop_monitor_does_not_try_to_verify_a_too_small_image(tmp_path):
    frame = Image.new("RGB", (1280, 720), (18, 24, 32))
    frame.paste(_pattern((120, 50), (35, 120, 170)), (900, 600))
    result = _run_completion(
        tmp_path, [(frame, None)], config={"dropStopNum": 0, "dropImage": "drop/item.png"},
        drop_template=Image.new("RGB", (1, 1), "red"),
    )
    assert result.status == JobStatus.SUCCEEDED
    assert result.result["complete"] is True
    assert result.result["drop_count"] == 0


def test_too_small_drop_template_fails_with_clear_error_before_matching(tmp_path):
    from webapp.core.errors import AppError, ErrorCode

    with pytest.raises(AppError) as raised:
        _recognizer(tmp_path, source=Image.new("RGB", (1, 1), "red"))
    assert raised.value.code == ErrorCode.TEMPLATE_LOAD_FAILED


@pytest.mark.parametrize("width,local_x,accepted", [(117, 36, True), (115, 35, False)])
def test_drop_center_rounds_local_half_pixel_before_global_offset(tmp_path, monkeypatch, width, local_x, accepted):
    _source, recognition, drops = _recognizer(tmp_path)
    candidate = MatchResult("drop/item.png", True, 0.9, 0.65, [101, 203], [width, 125], [0, 0])
    monkeypatch.setattr(recognition, "match_template_all", lambda *args, **kwargs: [candidate])
    monkeypatch.setattr(recognition, "match_templates", lambda *args, **kwargs: [
        MatchResult("drop/item.png", True, 0.9, 0.65, [101 + local_x, 234], [57, 62], [0, 0]),
    ])
    report = drops.recognize(_png(Image.new("RGB", (1280, 720))))
    assert bool(report["matches"]) is accepted


@pytest.mark.parametrize("cancel_at,expected_batches", [(2, []), (3, [16]), (4, [16])])
def test_drop_cancellation_before_after_and_between_center_batches(tmp_path, monkeypatch, cancel_at, expected_batches):
    _source, recognition, drops = _recognizer(tmp_path)
    candidate = MatchResult("drop/item.png", True, 0.9, 0.65, [0, 0], [176, 193], [88, 96])
    monkeypatch.setattr(recognition, "match_template_all", lambda *args, **kwargs: [candidate] * 35)
    batches = []
    checks = []

    def centers(_screen, options):
        batches.append(len(options))
        return [MatchResult("drop/item.png", True, 0.9, 0.65, [44, 48], [88, 96], [88, 96])] * len(options)

    def cancel():
        checks.append(1)
        if len(checks) == cancel_at:
            raise RuntimeError("cancelled")

    monkeypatch.setattr(recognition, "match_templates", centers)
    with pytest.raises(RuntimeError, match="cancelled"):
        drops.recognize(_png(Image.new("RGB", (1280, 720))), check_cancelled=cancel)
    assert batches == expected_batches
