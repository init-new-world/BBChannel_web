from __future__ import annotations

from collections.abc import Callable
from typing import Any

from webapp.core.errors import AppError, ErrorCode
from webapp.services.recognition import RecognitionService
from webapp.services.resources import ResourceService


class DropRecognizer:
    def __init__(self, resources: ResourceService, recognition: RecognitionService, template_path: str) -> None:
        self._recognition = recognition
        self._template_path = template_path
        metadata = resources.template_metadata(template_path)
        width, height = int(metadata["width"]), int(metadata["height"])
        # Original FGObattle.getDropTemp derives both reference resolutions from this mean.
        scale = (width / 176 + height / 193) / 2
        self._resolution = (int(1920 * scale), int(1080 * scale))
        self._center_resolution = (int(176 * scale), int(193 * scale))
        self._crop = (width // 4, height // 4, 3 * width // 4, 3 * height // 4)
        if (not all(value > 0 for value in (*self._resolution, *self._center_resolution))
                or self._crop[0] >= self._crop[2] or self._crop[1] >= self._crop[3]):
            raise AppError(ErrorCode.TEMPLATE_LOAD_FAILED, "Drop template is too small for center verification.")

    def recognize(self, screenshot: bytes, *, check_cancelled: Callable[[], None] | None = None) -> dict[str, Any]:
        checkpoint = check_cancelled or (lambda: None)
        checkpoint()
        screen_width, screen_height = self._recognition.image_size(screenshot)
        scale = min(screen_width / self._resolution[0], screen_height / self._resolution[1])
        candidates = self._recognition.match_template_all(
            screenshot, self._template_path, threshold=0.65,
            scales=(scale,), grayscale=False, max_results=100,
            use_alpha_mask=False,
        )
        verified = []
        center_rejected = 0
        offset_rejected = 0
        for start in range(0, len(candidates), 16):
            checkpoint()
            group = candidates[start:start + 16]
            options = [{
                "template_path": self._template_path,
                "threshold": 0.65,
                "roi": [*candidate.top_left, *candidate.size],
                "template_crop": self._crop,
                "grayscale": True,
                "use_alpha_mask": False,
                "scales": (min(candidate.size[0] / self._center_resolution[0],
                               candidate.size[1] / self._center_resolution[1]),),
            } for candidate in group]
            centers = self._recognition.match_templates(screenshot, options)
            checkpoint()
            for candidate, center in zip(group, centers, strict=True):
                if not center.matched:
                    center_rejected += 1
                    continue
                width, height = candidate.size
                local_x = round(center.top_left[0] - candidate.top_left[0] + center.size[0] / 2)
                local_y = round(center.top_left[1] - candidate.top_left[1] + center.size[1] / 2)
                distance = (local_x - width / 2) ** 2 + (local_y - height / 2) ** 2
                if distance > min(50, max(30, height / 193 * 50)):
                    offset_rejected += 1
                else:
                    verified.append(candidate)
        checkpoint()
        return {
            "matches": verified,
            "candidate_count": len(candidates),
            "center_rejected_count": center_rejected,
            "offset_rejected_count": offset_rejected,
        }
