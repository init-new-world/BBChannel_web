from __future__ import annotations

from typing import Any

from webapp.core.models import MatchResult
from webapp.services.recognition import RecognitionService


FREE_QUEST_SCALES = (1.0, 0.75, 2 / 3, 0.5)
FREE_QUEST_LIST_ROI = (600, 0, 200, 720)
FREE_QUEST_LAYOUT_SCALE = 2 / 3


class QuestRecognizer:
    def __init__(self, recognition: RecognitionService) -> None:
        self._recognition = recognition

    def recognize_free_quests(
        self,
        screenshot: bytes,
        server: str,
        *,
        threshold: float = 0.8,
    ) -> dict[str, Any]:
        normalized_server = server.strip().upper()
        if normalized_server not in {"CH", "CNTW", "JP"}:
            raise ValueError("server must be CH, CNTW, or JP.")

        matches: list[MatchResult] = []
        for template_name in ("freeQuest", "freeQuest1"):
            matches.extend(
                self._recognition.match_template_all(
                    screenshot,
                    f"battle/Free/{normalized_server}/{template_name}.png",
                    threshold=threshold,
                    roi=FREE_QUEST_LIST_ROI,
                    scales=FREE_QUEST_SCALES,
                    max_results=20,
                )
            )

        candidates = []
        for match in self._distinct_matches(matches):
            clear_result = self._recognition.match_template(
                screenshot,
                f"battle/Free/{normalized_server}/clear.png",
                threshold=threshold,
                roi=self._clear_roi(match.center),
                scales=(FREE_QUEST_LAYOUT_SCALE,),
                template_size=(160, 50),
            )
            candidates.append(
                {
                    "center": list(match.center),
                    "template_path": match.template_path,
                    "confidence": match.confidence,
                    "cleared": clear_result.matched,
                    "clear_confidence": clear_result.confidence,
                }
            )

        selected = next(
            (candidate for candidate in candidates if not candidate["cleared"]),
            None,
        )
        return {
            "server": normalized_server,
            "candidate_count": len(candidates),
            "candidates": candidates,
            "selected": selected,
        }

    @staticmethod
    def _distinct_matches(matches: list[MatchResult]) -> list[MatchResult]:
        ordered = sorted(matches, key=lambda match: (match.center[1], match.center[0]))
        distinct: list[MatchResult] = []
        for match in ordered:
            duplicate = next(
                (
                    existing
                    for existing in distinct
                    if abs(existing.center[0] - match.center[0]) <= 20
                    and abs(existing.center[1] - match.center[1]) <= 20
                ),
                None,
            )
            if duplicate is None:
                distinct.append(match)
            elif match.confidence > duplicate.confidence:
                distinct[distinct.index(duplicate)] = match
        return sorted(distinct, key=lambda match: (match.center[1], match.center[0]))

    @staticmethod
    def _clear_roi(center: list[int]) -> tuple[int, int, int, int]:
        left = round(center[0] - 80 * FREE_QUEST_LAYOUT_SCALE)
        top = round(center[1] + 75 * FREE_QUEST_LAYOUT_SCALE)
        right = round(center[0] + 80 * FREE_QUEST_LAYOUT_SCALE)
        bottom = round(center[1] + 125 * FREE_QUEST_LAYOUT_SCALE)
        return left, top, right - left + 1, bottom - top + 1
