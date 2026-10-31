from __future__ import annotations

import math
from typing import Any

from webapp.core.errors import AppError, ErrorCode
from webapp.services.recognition import RecognitionService

try:
    import cv2
    import numpy as np
except ImportError:  # pragma: no cover - dependency availability is environment-specific
    cv2 = None
    np = None


_DIGIT_SIZES = {
    "CH": ((19, 28), (15, 28), (19, 28), (19, 29), (20, 29),
           (18, 28), (20, 29), (19, 28), (20, 29), (20, 29)),
    "JP": ((21, 27), (19, 27), (20, 27), (19, 27), (21, 27),
           (19, 27), (21, 27), (18, 27), (19, 27), (21, 27)),
    "CNTW": ((18, 27), (19, 27), (18, 27), (18, 27), (19, 27),
             (18, 27), (18, 27), (18, 27), (18, 27), (17, 27)),
}
_ORIGINS = {"CH": (381, 984), "JP": (383, 984), "CNTW": (389, 986)}


def _partial_crop(server: str, digit: int) -> tuple[int, int, int, int]:
    width, height = _DIGIT_SIZES[server][digit]
    if server == "CNTW" and digit == 4:
        return 0, 0, 12, height
    if digit in {1, 2, 4}:
        return 0, 17, width, height
    if digit in {3, 5}:
        return 0, 0, 7, height
    if digit == 9:
        return 0, 14, width, height
    return 0, 0, width, {0: 18, 6: 17, 7: 13, 8: 17}[digit]


class NpChargeRecognizer:
    def __init__(self, recognition: RecognitionService) -> None:
        self._recognition = recognition

    def recognize(
        self,
        screenshot: bytes,
        server: str,
        *,
        present: tuple[bool, bool, bool] | list[bool],
        threshold: float | None = None,
    ) -> dict[str, Any]:
        if not isinstance(server, str) or server.upper() not in _ORIGINS:
            raise ValueError(f"Unsupported server: {server}")
        server = server.upper()
        if not isinstance(present, (list, tuple)) or len(present) != 3 or any(type(flag) is not bool for flag in present):
            raise ValueError("present must contain exactly three booleans.")
        if threshold is None:
            threshold = 0.75 if server == "CH" else 0.6
        if isinstance(threshold, bool) or not isinstance(threshold, (int, float)) or not 0 <= threshold <= 1:
            raise ValueError("threshold must be a finite number between 0 and 1.")
        if cv2 is None or np is None:
            raise AppError(ErrorCode.OPENCV_UNAVAILABLE, "OpenCV and NumPy are required for NP recognition.")
        if not isinstance(screenshot, bytes) or not screenshot:
            raise ValueError("Screenshot image could not be decoded.")
        try:
            image = cv2.imdecode(np.frombuffer(screenshot, dtype=np.uint8), cv2.IMREAD_COLOR)
        except cv2.error as exc:
            raise ValueError("Screenshot image could not be decoded.") from exc
        if image is None:
            raise ValueError("Screenshot image could not be decoded.")
        if image.shape[:2] != (720, 1280):
            raise ValueError("NP recognition requires a normalized 1280 by 720 screenshot.")

        values: list[int | None] = [0, 0, 0]
        origin_x, origin_y = _ORIGINS[server]
        for position, occupied in enumerate(present):
            if not occupied:
                continue
            advance = 0
            value = 0
            for place in range(3):
                # Transform each original corner, not a separately rounded advance.
                left = round((origin_x + 476 * position - advance) * (2 / 3))
                right = round((origin_x + 476 * position - advance + 30) * (2 / 3))
                top = round(origin_y * (2 / 3))
                bottom = round((origin_y + 33) * (2 / 3))
                crop = cv2.resize(image[top:bottom, left:right], (30, 33), interpolation=cv2.INTER_LINEAR)
                encoded, png = cv2.imencode(".png", crop)
                if not encoded:
                    raise ValueError("NP digit crop could not be encoded.")
                digit = self._digit(png.tobytes(), server, float(threshold))
                if digit is None and place == 0:
                    values[position] = None
                    break
                digit = digit if digit is not None else 0
                value += digit * 10 ** place
                advance += (15 if digit == 1 else 20) if server == "CH" else 21 if server == "JP" else 17
            else:
                values[position] = value
        return {"values": values, "complete": all(value is not None for value in values)}

    def _digit(self, screenshot: bytes, server: str, threshold: float) -> int | None:
        def candidates(digits, *, partial=False):
            result = []
            for digit in digits:
                prefix = f"battle/{server}/digits"
                candidate = {
                    "template_path": f"{prefix}/{digit}.png",
                    "mask_path": f"{prefix}/mask{digit}.png",
                    "threshold": 0 if partial else threshold,
                    "grayscale": True,
                    "scales": (1.0,),
                }
                if partial:
                    candidate["template_crop"] = _partial_crop(server, digit)
                result.append(candidate)
            return result

        matches = self._recognition.match_templates(screenshot, candidates(range(10)))
        ranked = sorted(
            ((digit, match.confidence) for digit, match in zip(range(10), matches, strict=True)
             if match.matched and math.isfinite(match.confidence) and match.confidence >= threshold),
            key=lambda item: item[1], reverse=True,
        )
        if not ranked:
            return None
        first = ranked[0][0]
        if len(ranked) == 1 or ranked[0][1] - ranked[1][1] > 0.1:
            return first
        digits = [first, ranked[1][0]]
        partial = self._recognition.match_templates(screenshot, candidates(digits, partial=True))
        ranked_partial = sorted(
            ((digit, match.confidence) for digit, match in zip(digits, partial, strict=True)
             if match.matched and math.isfinite(match.confidence) and match.confidence > 0),
            key=lambda item: item[1], reverse=True,
        )
        return ranked_partial[0][0] if ranked_partial else first
