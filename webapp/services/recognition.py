from __future__ import annotations

import math
from collections.abc import Sequence
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
        roi: Sequence[int] | None = None,
        scales: Sequence[float] | None = None,
        mask_path: str | None = None,
    ) -> MatchResult:
        screenshot_image = self._decode_screenshot(screenshot, template_path)
        return self._match_decoded(
            screenshot_image,
            template_path,
            threshold=threshold,
            roi=roi,
            scales=scales,
            mask_path=mask_path,
        )

    def match_templates(
        self,
        screenshot: bytes,
        candidates: Sequence[dict[str, object]],
    ) -> list[MatchResult]:
        screenshot_image = self._decode_screenshot(screenshot, None)
        results: list[MatchResult] = []
        for candidate in candidates:
            template_path = str(candidate["template_path"])
            results.append(
                self._match_decoded(
                    screenshot_image,
                    template_path,
                    threshold=float(candidate.get("threshold", 0.8)),
                    roi=candidate.get("roi"),
                    scales=candidate.get("scales"),
                    mask_path=(
                        str(candidate["mask_path"])
                        if candidate.get("mask_path") is not None
                        else None
                    ),
                )
            )
        return results

    def match_template_debug(
        self,
        screenshot: bytes,
        template_path: str,
        threshold: float = 0.8,
        roi: Sequence[int] | None = None,
        scales: Sequence[float] | None = None,
    ) -> tuple[MatchResult, bytes]:
        cv, _ = self._require_opencv()
        screenshot_image = self._decode_screenshot(screenshot, template_path)
        result = self._match_decoded(
            screenshot_image,
            template_path,
            threshold=threshold,
            roi=roi,
            scales=scales,
        )
        overlay = screenshot_image.copy()
        if result.roi is not None:
            roi_x, roi_y, roi_width, roi_height = result.roi
            cv.rectangle(
                overlay,
                (roi_x, roi_y),
                (roi_x + roi_width - 1, roi_y + roi_height - 1),
                (255, 210, 0),
                1,
            )
        x, y = result.top_left
        width, height = result.size
        match_color = (55, 190, 70) if result.matched else (0, 145, 255)
        cv.rectangle(
            overlay,
            (x, y),
            (x + width - 1, y + height - 1),
            match_color,
            2,
        )
        cv.circle(overlay, tuple(result.center), 4, match_color, -1)
        label = f"{result.confidence:.3f}  {result.scale:.2f}x"
        font = cv.FONT_HERSHEY_SIMPLEX
        font_scale = 0.5
        thickness = 1
        (label_width, label_height), baseline = cv.getTextSize(
            label,
            font,
            font_scale,
            thickness,
        )
        label_x = max(x, 0)
        label_y = y - 6 if y - label_height - baseline - 8 >= 0 else y + label_height + 8
        background_top = label_y - label_height - 4
        cv.rectangle(
            overlay,
            (label_x, background_top),
            (label_x + label_width + 6, label_y + baseline + 2),
            (22, 28, 35),
            -1,
        )
        cv.putText(
            overlay,
            label,
            (label_x + 3, label_y),
            font,
            font_scale,
            (255, 255, 255),
            thickness,
            cv.LINE_AA,
        )
        encoded, png = cv.imencode(".png", overlay)
        if not encoded:
            raise AppError(
                ErrorCode.MATCH_FAILED,
                "Recognition debug overlay could not be encoded.",
                {"template_path": template_path},
            )
        return result, png.tobytes()

    def _decode_screenshot(self, screenshot: bytes, template_path: str | None):
        cv, numpy = self._require_opencv()
        screenshot_image = cv.imdecode(
            numpy.frombuffer(screenshot, dtype=numpy.uint8),
            cv.IMREAD_COLOR,
        )
        if screenshot_image is None:
            raise AppError(
                ErrorCode.MATCH_FAILED,
                "Screenshot image could not be decoded.",
                {"template_path": template_path} if template_path is not None else {},
            )
        return screenshot_image

    def _match_decoded(
        self,
        screenshot_image,
        template_path: str,
        *,
        threshold: float,
        roi: object = None,
        scales: object = None,
        mask_path: str | None = None,
    ) -> MatchResult:
        cv, numpy = self._require_opencv()
        template_file = self._resources.resolve_template(template_path)
        template_source = cv.imread(str(template_file), cv.IMREAD_UNCHANGED)
        if template_source is None:
            raise AppError(
                ErrorCode.TEMPLATE_LOAD_FAILED,
                f"Template image could not be loaded: {template_path}",
                {"template_path": template_path},
            )
        template_mask = None
        explicit_mask = mask_path is not None
        if len(template_source.shape) == 3 and template_source.shape[2] == 4:
            alpha = template_source[:, :, 3]
            template_image = template_source[:, :, :3]
            if int(alpha.min()) < 255:
                template_mask = alpha
        elif len(template_source.shape) == 2:
            template_image = cv.cvtColor(template_source, cv.COLOR_GRAY2BGR)
        else:
            template_image = template_source

        if mask_path is not None:
            mask_file = self._resources.resolve_template(mask_path)
            template_mask = cv.imread(str(mask_file), cv.IMREAD_GRAYSCALE)
            if template_mask is None:
                raise AppError(
                    ErrorCode.TEMPLATE_LOAD_FAILED,
                    f"Template mask could not be loaded: {mask_path}",
                    {"template_path": template_path, "mask_path": mask_path},
                )
            if template_mask.shape[:2] != template_image.shape[:2]:
                raise AppError(
                    ErrorCode.MATCH_FAILED,
                    "Template mask dimensions must match the template.",
                    {
                        "template_path": template_path,
                        "mask_path": mask_path,
                        "template_size": [template_image.shape[1], template_image.shape[0]],
                        "mask_size": [template_mask.shape[1], template_mask.shape[0]],
                    },
                )

        screenshot_height, screenshot_width = screenshot_image.shape[:2]
        normalized_roi = self._normalize_roi(
            roi,
            screenshot_width,
            screenshot_height,
            template_path,
        )
        roi_x, roi_y, roi_width, roi_height = normalized_roi
        search_image = screenshot_image[roi_y : roi_y + roi_height, roi_x : roi_x + roi_width]
        normalized_scales = self._normalize_scales(scales, template_path)

        best: tuple[float, tuple[int, int], int, int, float] | None = None
        template_height, template_width = template_image.shape[:2]
        for scale in normalized_scales:
            scaled_width = max(round(template_width * scale), 1)
            scaled_height = max(round(template_height * scale), 1)
            if scaled_width > roi_width or scaled_height > roi_height:
                continue
            if scaled_width == template_width and scaled_height == template_height:
                scaled_template = template_image
                scaled_mask = template_mask
            else:
                interpolation = cv.INTER_AREA if scale < 1 else cv.INTER_LINEAR
                scaled_template = cv.resize(
                    template_image,
                    (scaled_width, scaled_height),
                    interpolation=interpolation,
                )
                scaled_mask = (
                    cv.resize(
                        template_mask,
                        (scaled_width, scaled_height),
                        interpolation=cv.INTER_NEAREST,
                    )
                    if template_mask is not None
                    else None
                )
            if scaled_mask is None:
                matches = cv.matchTemplate(
                    search_image,
                    scaled_template,
                    cv.TM_CCOEFF_NORMED,
                )
            else:
                matches = cv.matchTemplate(
                    search_image,
                    scaled_template,
                    cv.TM_CCOEFF_NORMED if explicit_mask else cv.TM_CCORR_NORMED,
                    mask=scaled_mask,
                )
                matches = numpy.nan_to_num(
                    matches,
                    nan=-1.0,
                    posinf=-1.0,
                    neginf=-1.0,
                )
            _, confidence, _, max_location = cv.minMaxLoc(matches)
            candidate = (
                float(confidence),
                max_location,
                scaled_width,
                scaled_height,
                scale,
            )
            if best is None or candidate[0] > best[0]:
                best = candidate

        if best is None:
            raise AppError(
                ErrorCode.MATCH_FAILED,
                "Template is larger than the selected screenshot region at every scale.",
                {
                    "template_path": template_path,
                    "roi": normalized_roi,
                    "scales": normalized_scales,
                },
            )

        confidence, max_location, matched_width, matched_height, best_scale = best
        top_left = [roi_x + int(max_location[0]), roi_y + int(max_location[1])]
        result_roi = normalized_roi if roi is not None else None
        return MatchResult(
            template_path=template_path,
            matched=confidence >= threshold,
            confidence=confidence,
            threshold=threshold,
            top_left=top_left,
            size=[matched_width, matched_height],
            center=[top_left[0] + matched_width // 2, top_left[1] + matched_height // 2],
            scale=best_scale,
            roi=result_roi,
        )

    @staticmethod
    def _normalize_roi(
        roi: object,
        screenshot_width: int,
        screenshot_height: int,
        template_path: str,
    ) -> list[int]:
        if roi is None:
            return [0, 0, screenshot_width, screenshot_height]
        try:
            values = [int(value) for value in roi]  # type: ignore[union-attr]
        except (TypeError, ValueError) as exc:
            raise RecognitionService._invalid_roi(template_path, roi) from exc
        if len(values) != 4:
            raise RecognitionService._invalid_roi(template_path, roi)
        x, y, width, height = values
        if (
            x < 0
            or y < 0
            or width <= 0
            or height <= 0
            or x + width > screenshot_width
            or y + height > screenshot_height
        ):
            raise RecognitionService._invalid_roi(template_path, roi)
        return values

    @staticmethod
    def _invalid_roi(template_path: str, roi: object) -> AppError:
        return AppError(
            ErrorCode.MATCH_FAILED,
            "ROI must be [x, y, width, height] inside the screenshot.",
            {"template_path": template_path, "roi": roi},
        )

    @staticmethod
    def _normalize_scales(scales: object, template_path: str) -> list[float]:
        if scales is None:
            return [1.0]
        try:
            values = [float(value) for value in scales]  # type: ignore[union-attr]
        except (TypeError, ValueError) as exc:
            raise RecognitionService._invalid_scales(template_path, scales) from exc
        if not values or any(value <= 0 or not math.isfinite(value) for value in values):
            raise RecognitionService._invalid_scales(template_path, scales)
        return list(dict.fromkeys(values))

    @staticmethod
    def _invalid_scales(template_path: str, scales: object) -> AppError:
        return AppError(
            ErrorCode.MATCH_FAILED,
            "Template scales must contain positive finite numbers.",
            {"template_path": template_path, "scales": scales},
        )

    def _require_opencv(self) -> tuple[Any, Any]:
        if cv2 is None or np is None:
            raise AppError(
                ErrorCode.OPENCV_UNAVAILABLE,
                "OpenCV and NumPy are required for template recognition.",
            )
        return cv2, np
