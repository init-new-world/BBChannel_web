from __future__ import annotations

import base64

from webapp.core.errors import AppError, ErrorCode
from webapp.devices.coordinates import FrameNormalizer
from webapp.services.cards import CARD_ORIGIN_X
from webapp.services.image_tags import ImageTagService, _bounds
from webapp.services.resources import ResourceService


class CommandTagService(ImageTagService):
    def __init__(self, resources: ResourceService) -> None:
        super().__init__(resources, directory="battle/customCommandCard", kind="Command tag")
        self._normalizer = FrameNormalizer()

    @staticmethod
    def candidates() -> list[dict[str, object]]:
        candidates = []
        for slot, origin_x in enumerate(CARD_ORIGIN_X, start=1):
            left, top = round(origin_x * 2 / 3), round(530 * 2 / 3)
            # A shared width avoids a rounded extra pixel that only fits slot 5.
            width, height = round(290 * 2 / 3), round(390 * 2 / 3)
            candidates.append({
                "slot": slot, "anchor": [left, top],
                "bounds": [left, top, width, height],
            })
        return candidates

    def capture(self, screenshot: bytes) -> dict[str, object]:
        normalized = self._normalizer.normalize(screenshot)
        candidates = self.candidates()
        return {
            "candidate_count": len(candidates), "candidates": candidates,
            "screenshot_base64": base64.b64encode(normalized.png).decode("ascii"),
        }

    def build_card(
        self, *, label: str, screenshot: bytes, slot: int, bounds: list[int],
        threshold: float, overwrite: bool = False,
    ) -> dict[str, object]:
        if isinstance(slot, bool) or not isinstance(slot, int) or not 1 <= slot <= 5:
            raise AppError(ErrorCode.DATA_FILE_INVALID, "Command tag slot must be between 1 and 5.")
        normalized = self._normalizer.normalize(screenshot)
        left, top, right, bottom = _bounds(bounds, (1280, 720))
        candidate = self.candidates()[slot - 1]
        x, y, width, height = candidate["bounds"]
        if not (x <= left < right <= x + width and y <= top < bottom <= y + height):
            raise AppError(
                ErrorCode.DATA_FILE_INVALID,
                "Command tag crop must be inside the selected card.",
                {"slot": slot, "bounds": bounds, "card_bounds": candidate["bounds"]},
            )
        return self.build(
            label=label, screenshot=normalized.png, anchor=candidate["anchor"],
            bounds=bounds, threshold=threshold, overwrite=overwrite,
        )
