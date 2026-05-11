from __future__ import annotations

from typing import Any

from webapp.core.errors import AppError, ErrorCode
from webapp.core.models import MatchResult
from webapp.services.resources import ResourceService

try:
    import cv2
except ImportError:  # pragma: no cover - exercised by dependency-absent tests
    cv2 = None  # type: ignore[assignment]

try:
    import numpy as np
except ImportError:  # pragma: no cover - exercised by dependency-absent tests
    np = None  # type: ignore[assignment]


class RecognitionService:
    def __init__(self, resources: ResourceService) -> None:
        self._resources = resources

    def match_template(
        self,
        screenshot: bytes,
        template_path: str,
        threshold: float = 0.8,
    ) -> MatchResult:
        cv, numpy = self._require_opencv()
        template_file = self._resources.resolve_template(template_path)

        screenshot_image = cv.imdecode(
            numpy.frombuffer(screenshot, dtype=numpy.uint8),
            cv.IMREAD_COLOR,
        )
        if screenshot_image is None:
            raise AppError(
                ErrorCode.MATCH_FAILED,
                "Screenshot image could not be decoded.",
                {"template_path": template_path},
            )

        template_image = cv.imread(str(template_file), cv.IMREAD_COLOR)
        if template_image is None:
            raise AppError(
                ErrorCode.TEMPLATE_LOAD_FAILED,
                f"Template image could not be loaded: {template_path}",
                {"template_path": template_path},
            )

        screenshot_height, screenshot_width = screenshot_image.shape[:2]
        template_height, template_width = template_image.shape[:2]
        if template_width > screenshot_width or template_height > screenshot_height:
            raise AppError(
                ErrorCode.MATCH_FAILED,
                "Template is larger than the screenshot.",
                {
                    "template_path": template_path,
                    "screenshot_size": [screenshot_width, screenshot_height],
                    "template_size": [template_width, template_height],
                },
            )

        matches = cv.matchTemplate(screenshot_image, template_image, cv.TM_CCOEFF_NORMED)
        _, confidence, _, max_location = cv.minMaxLoc(matches)
        top_left = [int(max_location[0]), int(max_location[1])]
        size = [int(template_width), int(template_height)]

        return MatchResult(
            template_path=template_path,
            matched=confidence >= threshold,
            confidence=float(confidence),
            threshold=threshold,
            top_left=top_left,
            size=size,
            center=[
                top_left[0] + template_width // 2,
                top_left[1] + template_height // 2,
            ],
        )

    def _require_opencv(self) -> tuple[Any, Any]:
        if cv2 is None or np is None:
            raise AppError(
                ErrorCode.OPENCV_UNAVAILABLE,
                "OpenCV and NumPy are required for template recognition.",
            )
        return cv2, np
