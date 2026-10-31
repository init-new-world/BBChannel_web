from types import SimpleNamespace

import pytest

cv2 = pytest.importorskip("cv2")
np = pytest.importorskip("numpy")

from webapp.services.np_charge import NpChargeRecognizer
from webapp.services.recognition import RecognitionService
from webapp.services.resources import ResourceService


_DIGIT_SIZES = {
    "CH": ((19, 28), (15, 28), (19, 28), (19, 29), (20, 29),
           (18, 28), (20, 29), (19, 28), (20, 29), (20, 29)),
    "JP": ((21, 27), (19, 27), (20, 27), (19, 27), (21, 27),
           (19, 27), (21, 27), (18, 27), (19, 27), (21, 27)),
    "CNTW": ((18, 27), (19, 27), (18, 27), (18, 27), (19, 27),
             (18, 27), (18, 27), (18, 27), (18, 27), (17, 27)),
}

# Literal expected corners from the original 1920-based transform at scale 2/3.
_POSITION_ROIS = {
    "CH": (
        ((254, 656, 20, 22), (241, 656, 20, 22), (227, 656, 20, 22)),
        ((571, 656, 20, 22), (558, 656, 20, 22), (545, 656, 20, 22)),
        ((889, 656, 20, 22), (875, 656, 20, 22), (862, 656, 20, 22)),
    ),
    "JP": (
        ((255, 656, 20, 22), (241, 656, 20, 22), (227, 656, 20, 22)),
        ((573, 656, 20, 22), (559, 656, 20, 22), (545, 656, 20, 22)),
        ((890, 656, 20, 22), (876, 656, 20, 22), (862, 656, 20, 22)),
    ),
    "CNTW": (
        ((259, 657, 20, 22), (248, 657, 20, 22), (237, 657, 20, 22)),
        ((577, 657, 20, 22), (565, 657, 20, 22), (554, 657, 20, 22)),
        ((894, 657, 20, 22), (883, 657, 20, 22), (871, 657, 20, 22)),
    ),
}


def _png(image):
    ok, encoded = cv2.imencode(".png", image)
    assert ok
    return encoded.tobytes()


@pytest.fixture(scope="module")
def frame():
    image = np.random.default_rng(481).integers(
        0, 256, size=(720, 1280, 3), dtype=np.uint8
    )
    return image, _png(image)


def _full(roi, results=None):
    return SimpleNamespace(
        roi=roi, digits=tuple(range(10)), results=results or {}, partial=False
    )


def _hit(roi, digit, confidence=1.0):
    return _full(roi, {digit: (True, confidence)})


def _partial(roi, digits, results):
    return SimpleNamespace(roi=roi, digits=digits, results=results, partial=True)


def _partial_crop(server, digit):
    width, height = _DIGIT_SIZES[server][digit]
    if server == "CNTW" and digit == 4:
        return (0, 0, 12, height)
    return {
        0: (0, 0, width, 18),
        1: (0, 17, width, height),
        2: (0, 17, width, height),
        3: (0, 0, 7, height),
        4: (0, 17, width, height),
        5: (0, 0, 7, height),
        6: (0, 0, width, 17),
        7: (0, 0, width, 13),
        8: (0, 0, width, 17),
        9: (0, 14, width, height),
    }[digit]


class _Matcher:
    def __init__(self, image, steps=(), *, server="CH", threshold=None):
        self.image = image
        self.steps = steps
        self.server = server.upper()
        self.threshold = (
            0.75 if self.server == "CH" else 0.6
        ) if threshold is None else threshold
        self.calls = 0

    def match_templates(self, screenshot, candidates):
        assert self.calls < len(self.steps), "Unexpected extra digit matching call."
        step = self.steps[self.calls]
        self.calls += 1
        assert isinstance(screenshot, bytes)
        assert screenshot.startswith(b"\x89PNG\r\n\x1a\n")
        actual = cv2.imdecode(np.frombuffer(screenshot, np.uint8), cv2.IMREAD_COLOR)
        assert actual is not None
        assert actual.shape == (33, 30, 3)
        x, y, width, height = step.roi
        expected = cv2.resize(
            self.image[y:y + height, x:x + width],
            (30, 33),
            interpolation=cv2.INTER_LINEAR,
        )
        np.testing.assert_array_equal(actual, expected)
        assert len(candidates) == len(step.digits)
        matches = []
        for digit, candidate in zip(step.digits, candidates, strict=True):
            prefix = f"battle/{self.server}/digits"
            assert candidate["template_path"] == f"{prefix}/{digit}.png"
            assert candidate["mask_path"] == f"{prefix}/mask{digit}.png"
            assert candidate["grayscale"] is True
            assert tuple(candidate["scales"]) == (1.0,)
            assert candidate["threshold"] == (0 if step.partial else self.threshold)
            assert candidate.get("template_size") is None
            roi = candidate.get("roi")
            assert roi is None or tuple(roi) == (0, 0, 30, 33)
            if step.partial:
                assert tuple(candidate["template_crop"]) == _partial_crop(
                    self.server, digit
                )
            else:
                assert candidate.get("template_crop") is None
            matched, confidence = step.results.get(digit, (False, -1.0))
            matches.append(SimpleNamespace(matched=matched, confidence=confidence))
        return matches


def _recognize(frame, steps, *, server="CH", present=(True, False, False), threshold=None):
    image, screenshot = frame
    matcher = _Matcher(image, steps, server=server, threshold=threshold)
    result = NpChargeRecognizer(matcher).recognize(
        screenshot, server, present=present, threshold=threshold
    )
    assert matcher.calls == len(steps)
    assert len(result["values"]) == 3
    assert all(value is None or type(value) is int for value in result["values"])
    assert type(result["complete"]) is bool
    return result


def _zero_tail(server):
    return [_full(roi) for roi in _POSITION_ROIS[server][0][1:]]


@pytest.mark.parametrize("server", ["CH", "ch", "Ch", "JP", "jp", "CNTW", "cntw"])
def test_server_case_normalization_and_default_confidence(frame, server):
    normalized = server.upper()
    confidence = 0.75 if normalized == "CH" else 0.6
    steps = [
        _hit(_POSITION_ROIS[normalized][0][0], 0, confidence),
        *_zero_tail(normalized),
    ]

    assert _recognize(frame, steps, server=server) == {
        "values": [0, 0, 0], "complete": True
    }


@pytest.mark.parametrize("server", ["", "EN", "CN", "CHN"])
def test_unsupported_server_is_rejected_before_matching(frame, server):
    matcher = _Matcher(frame[0])

    with pytest.raises(ValueError):
        NpChargeRecognizer(matcher).recognize(
            frame[1], server, present=(False, False, False)
        )

    assert matcher.calls == 0


@pytest.mark.parametrize(
    "present",
    [
        None, (), (True, False), (True, False, False, False),
        (1, False, False), (False, "", False), (False, None, False),
        (np.bool_(True), False, False), {0: True, 1: False, 2: False},
    ],
)
def test_present_requires_exactly_three_primitive_booleans(frame, present):
    matcher = _Matcher(frame[0])

    with pytest.raises(ValueError):
        NpChargeRecognizer(matcher).recognize(frame[1], "CH", present=present)

    assert matcher.calls == 0


@pytest.mark.parametrize("present", [(False, False, False), [False, False, False]])
def test_all_absent_positions_are_zero_without_matching(frame, present):
    assert _recognize(frame, [], present=present) == {
        "values": [0, 0, 0], "complete": True
    }


@pytest.mark.parametrize(
    "threshold",
    [True, False, "0.75", -0.001, 1.001, float("nan"), float("inf"), -float("inf")],
)
def test_invalid_threshold_is_rejected_before_matching(frame, threshold):
    matcher = _Matcher(frame[0])

    with pytest.raises(ValueError):
        NpChargeRecognizer(matcher).recognize(
            frame[1], "CH", present=(False, False, False), threshold=threshold
        )

    assert matcher.calls == 0


@pytest.mark.parametrize(("threshold", "digit"), [(0, 4), (1, 9), (0.8, 6)])
def test_explicit_threshold_is_inclusive_and_overrides_default(frame, threshold, digit):
    steps = [_hit(_POSITION_ROIS["CH"][0][0], digit, threshold), *_zero_tail("CH")]

    assert _recognize(frame, steps, threshold=threshold) == {
        "values": [digit, 0, 0], "complete": True
    }


@pytest.mark.parametrize("screenshot", [b"", b"not an image", b"\x89PNG\r\n\x1a\n"])
def test_invalid_screenshot_bytes_raise_value_error(frame, screenshot):
    matcher = _Matcher(frame[0])

    with pytest.raises(ValueError):
        NpChargeRecognizer(matcher).recognize(
            screenshot, "CH", present=(False, False, False)
        )

    assert matcher.calls == 0


@pytest.mark.parametrize("size", [(1920, 1080), (720, 1280), (1280, 719), (1279, 720)])
def test_only_normalized_1280_by_720_frames_are_accepted(frame, size):
    width, height = size
    screenshot = _png(np.zeros((height, width, 3), dtype=np.uint8))
    matcher = _Matcher(frame[0])

    with pytest.raises(ValueError):
        NpChargeRecognizer(matcher).recognize(
            screenshot, "CH", present=(False, False, False)
        )

    assert matcher.calls == 0


@pytest.mark.parametrize("server", ["CH", "JP", "CNTW"])
def test_each_physical_position_uses_independently_rounded_corners(frame, server):
    steps = []
    for rois, digits in zip(
        _POSITION_ROIS[server], ((3, 2, 1), (5, 4, None), (6, None, None)), strict=True
    ):
        for roi, digit in zip(rois, digits, strict=True):
            steps.append(_full(roi) if digit is None else _hit(roi, digit))

    assert _recognize(frame, steps, server=server, present=(True, True, True)) == {
        "values": [123, 45, 6], "complete": True
    }


@pytest.mark.parametrize(
    ("units", "tens", "tens_x", "hundreds_x", "value"),
    [(1, 1, 244, 234, 111), (1, 0, 244, 231, 101),
     (0, 1, 241, 231, 110), (2, 2, 241, 227, 122)],
)
def test_ch_advance_depends_on_each_previously_recognized_digit(
    frame, units, tens, tens_x, hundreds_x, value
):
    steps = [
        _hit((254, 656, 20, 22), units),
        _hit((tens_x, 656, 20, 22), tens),
        _hit((hundreds_x, 656, 20, 22), 1),
    ]

    assert _recognize(frame, steps) == {"values": [value, 0, 0], "complete": True}


def test_missing_tens_still_reads_hundreds_with_zero_digit_advance(frame):
    steps = [
        _hit((254, 656, 20, 22), 1),
        _full((244, 656, 20, 22)),
        _hit((231, 656, 20, 22), 2),
    ]

    assert _recognize(frame, steps) == {"values": [201, 0, 0], "complete": True}


def test_missing_units_stops_only_that_position_and_preserves_absent_slot(frame):
    steps = [
        _full((254, 656, 20, 22)),
        _hit((889, 656, 20, 22), 0),
        _full((875, 656, 20, 22)),
        _full((862, 656, 20, 22)),
    ]

    assert _recognize(frame, steps, present=(True, False, True)) == {
        "values": [None, 0, 0], "complete": False
    }


def test_numeric_assembly_is_not_clamped_to_300(frame):
    steps = [_hit(roi, 9) for roi in _POSITION_ROIS["CH"][0]]

    assert _recognize(frame, steps) == {"values": [999, 0, 0], "complete": True}


@pytest.mark.parametrize(
    ("results", "digit"),
    [
        ({2: (True, 0.75), 4: (True, 0.749999)}, 2),
        ({2: (False, 1.0), 6: (True, 0.8)}, 6),
        ({0: (True, float("nan")), 1: (True, float("inf")),
          2: (True, -float("inf")), 6: (True, 0.9)}, 6),
    ],
    ids=["threshold-before-runner-up", "matched-flag", "nonfinite-safety"],
)
def test_full_ranking_uses_only_matched_finite_threshold_eligible_scores(
    frame, results, digit
):
    steps = [_full((254, 656, 20, 22), results), *_zero_tail("CH")]

    assert _recognize(frame, steps) == {"values": [digit, 0, 0], "complete": True}


def test_no_eligible_full_digit_returns_unknown_without_higher_digit_reads(frame):
    results = {
        0: (True, float("nan")), 1: (True, float("inf")),
        2: (True, -float("inf")), 3: (False, 1.0),
        4: (True, 0.749999), 5: (True, -0.1),
    }

    assert _recognize(frame, [_full((254, 656, 20, 22), results)]) == {
        "values": [None, 0, 0], "complete": False
    }


@pytest.mark.parametrize(
    ("runner_score", "needs_partial", "digit"),
    [(0.95, True, 4), (0.9, True, 4), (0.899, False, 2)],
    ids=["inside-margin", "boundary-margin", "outside-margin"],
)
def test_only_top_two_with_margin_at_most_point_one_trigger_partial_ranking(
    frame, runner_score, needs_partial, digit
):
    roi = (254, 656, 20, 22)
    steps = [_full(roi, {2: (True, 1.0), 4: (True, runner_score)})]
    if needs_partial:
        steps.append(_partial(roi, (2, 4), {2: (True, 0.4), 4: (True, 0.5)}))
    steps.extend(_zero_tail("CH"))

    assert _recognize(frame, steps) == {"values": [digit, 0, 0], "complete": True}


def test_equal_full_and_partial_scores_keep_stable_digit_order(frame):
    roi = (254, 656, 20, 22)
    steps = [
        _full(roi, {4: (True, 0.9), 2: (True, 0.9)}),
        _partial(roi, (2, 4), {2: (True, 0.5), 4: (True, 0.5)}),
        *_zero_tail("CH"),
    ]

    assert _recognize(frame, steps) == {"values": [2, 0, 0], "complete": True}


@pytest.mark.parametrize("server", ["CH", "JP", "CNTW"])
@pytest.mark.parametrize("digits", [(0, 1), (2, 3), (4, 5), (6, 7), (8, 9)])
def test_all_partial_features_crop_native_template_and_mask_not_search_image(
    frame, server, digits
):
    first, second = digits
    roi = _POSITION_ROIS[server][0][0]
    steps = [
        _full(roi, {first: (True, 0.9), second: (True, 0.85)}),
        _partial(roi, digits, {first: (True, 0.8), second: (True, 0.7)}),
        *_zero_tail(server),
    ]

    assert _recognize(frame, steps, server=server) == {
        "values": [first, 0, 0], "complete": True
    }


@pytest.mark.parametrize(
    ("first", "second", "digit"),
    [
        ((True, 0.3), (True, 0.8), 4),
        ((True, 0.8), (True, 0.8), 2),
        ((False, 0.99), (True, 0.1), 4),
        ((True, 0.0), (True, 0.0), 2),
        ((True, -0.1), (True, 0.0), 2),
        ((False, 0.8), (False, 0.9), 2),
        ((True, float("nan")), (True, float("inf")), 2),
        ((True, float("nan")), (True, 0.2), 4),
        ((True, 0.0), (True, 0.2), 4),
    ],
    ids=["runner-wins", "tie-keeps-first", "matched-flag", "zero-keeps-first",
         "negative-and-zero", "no-matches", "nonfinite-fallback",
         "finite-runner", "positive-over-zero"],
)
def test_partial_ranking_requires_a_positive_finite_matched_winner(
    frame, first, second, digit
):
    roi = (254, 656, 20, 22)
    steps = [
        _full(roi, {2: (True, 0.9), 4: (True, 0.85)}),
        _partial(roi, (2, 4), {2: first, 4: second}),
        *_zero_tail("CH"),
    ]

    assert _recognize(frame, steps) == {"values": [digit, 0, 0], "complete": True}


@pytest.mark.parametrize("server", ["CH", "JP", "CNTW"])
@pytest.mark.parametrize("position", [0, 1, 2])
def test_np_reader_uses_real_matcher_with_native_templates_and_explicit_masks(frame, tmp_path, server, position):
    image, screenshot = frame
    x, y, width, height = _POSITION_ROIS[server][position][0]
    search = cv2.resize(image[y:y + height, x:x + width], (30, 33), interpolation=cv2.INTER_LINEAR)
    assets = tmp_path / "assets"
    directory = assets / "battle" / server / "digits"
    directory.mkdir(parents=True)
    random = np.random.default_rng(611)
    for digit, (digit_width, digit_height) in enumerate(_DIGIT_SIZES[server]):
        template = random.integers(0, 256, (digit_height, digit_width, 3), dtype=np.uint8)
        mask = np.full((digit_height, digit_width), 255, dtype=np.uint8)
        mask[:2] = 0
        mask[:, :2] = 0
        if digit == 2:
            matching = search[2:2 + digit_height, 4:4 + digit_width]
            template[mask > 0] = matching[mask > 0]
        assert cv2.imwrite(str(directory / f"{digit}.png"), template)
        assert cv2.imwrite(str(directory / f"mask{digit}.png"), mask)
    recognition = RecognitionService(ResourceService(assets, tmp_path / "data"))
    result = NpChargeRecognizer(recognition).recognize(
        screenshot, server, present=tuple(index == position for index in range(3)), threshold=0.99
    )
    expected = [0, 0, 0]
    expected[position] = 2
    assert result == {"values": expected, "complete": True}


@pytest.mark.parametrize("dependency", ["cv2", "np"])
def test_np_reader_reports_missing_recognition_dependencies(frame, monkeypatch, dependency):
    from webapp.core.errors import AppError, ErrorCode
    from webapp.services import np_charge

    matcher = _Matcher(frame[0])
    monkeypatch.setattr(np_charge, dependency, None)
    with pytest.raises(AppError) as error:
        NpChargeRecognizer(matcher).recognize(frame[1], "CH", present=(False, False, False))
    assert error.value.code == ErrorCode.OPENCV_UNAVAILABLE
    assert matcher.calls == 0
