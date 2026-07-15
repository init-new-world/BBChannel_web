from __future__ import annotations

from typing import Any

from webapp.services.recognition import RecognitionService
from webapp.services.resources import ResourceService


ASSIST_FACE_SCALES = (1.0, 0.75, 2 / 3, 0.5)


class AssistRecognizer:
    def __init__(
        self,
        resources: ResourceService,
        recognition: RecognitionService,
    ) -> None:
        self._resources = resources
        self._recognition = recognition

    def recognize(
        self,
        screenshot: bytes,
        assist: dict[str, Any],
        *,
        threshold: float = 0.85,
    ) -> dict[str, Any]:
        canonical_name = assist.get("servant_canonical_name")
        templates = self._servant_templates(canonical_name)
        matches = [
            match
            for template_path in templates
            for match in self._recognition.match_template_all(
                screenshot,
                template_path,
                threshold=threshold,
                scales=ASSIST_FACE_SCALES,
                max_results=20,
            )
        ]

        candidates: list[dict[str, Any]] = []
        for match in sorted(matches, key=lambda result: result.confidence, reverse=True):
            candidate = {
                "bounds": [*match.top_left, *match.size],
                "anchor": list(match.center),
                "confidence": match.confidence,
                "template_path": match.template_path,
                "scale": match.scale,
            }
            if any(self._overlaps(candidate["bounds"], found["bounds"]) for found in candidates):
                continue
            candidates.append(candidate)

        candidates.sort(key=lambda candidate: (candidate["anchor"][1], candidate["anchor"][0]))
        return {
            "servant_name": assist.get("servant_name"),
            "servant_canonical_name": canonical_name,
            "servant_sn": assist.get("servant_sn"),
            "templates": templates,
            "candidates": candidates,
            "candidate_count": len(candidates),
        }

    def _servant_templates(self, canonical_name: Any) -> list[str]:
        if not isinstance(canonical_name, str) or not canonical_name:
            return []
        page = self._resources.template_index(
            prefix="servantface",
            query=canonical_name,
            limit=1000,
        )
        filename_prefix = f"{canonical_name}_"
        return [
            str(entry["path"])
            for entry in page["entries"]
            if str(entry["path"]).rsplit("/", 1)[-1].startswith(filename_prefix)
        ]

    @staticmethod
    def _overlaps(first: list[int], second: list[int]) -> bool:
        first_x, first_y, first_width, first_height = first
        second_x, second_y, second_width, second_height = second
        overlap_width = max(
            0,
            min(first_x + first_width, second_x + second_width) - max(first_x, second_x),
        )
        overlap_height = max(
            0,
            min(first_y + first_height, second_y + second_height) - max(first_y, second_y),
        )
        overlap_area = overlap_width * overlap_height
        if overlap_area == 0:
            return False
        union_area = first_width * first_height + second_width * second_height - overlap_area
        return overlap_area / union_area >= 0.3
