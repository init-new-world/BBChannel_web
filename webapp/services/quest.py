from __future__ import annotations

from typing import Any

from webapp.core.models import MatchResult
from webapp.services.recognition import RecognitionService


FREE_QUEST_SCALES = (1.0, 0.75, 2 / 3, 0.5)
FREE_QUEST_LIST_ROI = (600, 0, 200, 720)
FREE_QUEST_LAYOUT_SCALE = 2 / 3
INTERLUDE_AP_ROI = (700, 90, 233, 243)
INTERLUDE_GOTO_STAGE_ROI = (733, 87, 387, 273)
INTERLUDE_GOTO_INTERLUDE_ROI = (0, 80, 187, 100)
INTERLUDE_MISSION_TOUCH_POINT = (1048, 172)
INTERLUDE_RETURN_TOUCH_POINT = (105, 133)


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
            clear_roi = self._clear_roi(match.center)
            clear_result = (
                self._recognition.match_template(
                    screenshot,
                    f"battle/Free/{normalized_server}/clear.png",
                    threshold=threshold,
                    roi=clear_roi,
                    scales=(FREE_QUEST_LAYOUT_SCALE,),
                    template_size=(160, 50),
                )
                if clear_roi is not None
                else None
            )
            candidates.append(
                {
                    "center": list(match.center),
                    "template_path": match.template_path,
                    "confidence": match.confidence,
                    "cleared": clear_result.matched if clear_result is not None else False,
                    "clear_visible": clear_result is not None,
                    "clear_confidence": (
                        clear_result.confidence if clear_result is not None else None
                    ),
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

    def recognize_free_map(
        self,
        screenshot: bytes,
        *,
        threshold: float = 0.8,
    ) -> dict[str, Any]:
        matches = self._recognition.match_template_all(
            screenshot,
            "battle/Free/reddot.png",
            threshold=threshold,
            scales=FREE_QUEST_SCALES,
            mask_path="battle/Free/reddotMask.png",
            max_results=50,
        )
        candidates = []
        for match in sorted(matches, key=lambda item: (item.center[1], item.center[0])):
            x, y = match.center
            if (x < round(345 * FREE_QUEST_LAYOUT_SCALE) and y > 490) or y > round(
                830 * FREE_QUEST_LAYOUT_SCALE
            ):
                continue
            offset = round(40 * match.scale)
            candidates.append(
                {
                    "center": list(match.center),
                    "touch": [x - offset, y + offset],
                    "confidence": match.confidence,
                    "scale": match.scale,
                }
            )
        return {
            "candidate_count": len(candidates),
            "candidates": candidates,
            "selected": candidates[0] if candidates else None,
        }

    def recognize_main_story_quests(
        self,
        screenshot: bytes,
        server: str,
        *,
        threshold: float = 0.8,
    ) -> dict[str, Any]:
        normalized_server = server.strip().upper()
        if normalized_server not in {"CH", "CNTW", "JP"}:
            raise ValueError("server must be CH, CNTW, or JP.")

        template_root = f"battle/MainStory/{normalized_server}"
        matches = self._recognition.match_template_all(
            screenshot,
            f"{template_root}/reddot.png",
            threshold=threshold,
            scales=FREE_QUEST_SCALES,
            mask_path=f"{template_root}/reddotMask.png",
            max_results=50,
        )
        candidates = [
            {
                "center": list(match.center),
                "confidence": match.confidence,
                "scale": match.scale,
            }
            for match in self._distinct_matches(matches)
        ]
        return {
            "server": normalized_server,
            "candidate_count": len(candidates),
            "candidates": candidates,
            "selected": candidates[0] if candidates else None,
        }

    def recognize_interlude_quests(
        self,
        screenshot: bytes,
        server: str,
        *,
        threshold: float = 0.8,
        ap_threshold: float = 0.7,
    ) -> dict[str, Any]:
        normalized_server = server.strip().upper()
        if normalized_server not in {"CH", "CNTW", "JP"}:
            raise ValueError("server must be CH, CNTW, or JP.")

        goto_stage = self._recognition.match_template(
            screenshot,
            f"battle/Interlude/{normalized_server}/gotoStage.png",
            threshold=threshold,
            roi=INTERLUDE_GOTO_STAGE_ROI,
            scales=FREE_QUEST_SCALES,
        )
        ap_cost = self._recognition.match_template(
            screenshot,
            f"battle/{normalized_server}/AP.png",
            threshold=ap_threshold,
            roi=INTERLUDE_AP_ROI,
            scales=FREE_QUEST_SCALES,
        )
        goto_interlude = self._recognition.match_template(
            screenshot,
            f"battle/Interlude/{normalized_server}/gotoInterlude.png",
            threshold=threshold,
            roi=INTERLUDE_GOTO_INTERLUDE_ROI,
            scales=FREE_QUEST_SCALES,
        )

        selected: dict[str, Any] | None = None
        if goto_stage.matched:
            selected = {
                "action": "goto_stage",
                "center": list(goto_stage.center),
                "touch": list(INTERLUDE_MISSION_TOUCH_POINT),
                "confidence": goto_stage.confidence,
                "template_path": goto_stage.template_path,
            }
        elif ap_cost.matched:
            selected = {
                "action": "interlude_quest",
                "center": list(ap_cost.center),
                "touch": list(INTERLUDE_MISSION_TOUCH_POINT),
                "confidence": ap_cost.confidence,
                "template_path": ap_cost.template_path,
            }
        elif goto_interlude.matched:
            selected = {
                "action": "goto_interlude",
                "center": list(goto_interlude.center),
                "touch": list(INTERLUDE_RETURN_TOUCH_POINT),
                "confidence": goto_interlude.confidence,
                "template_path": goto_interlude.template_path,
            }

        return {
            "server": normalized_server,
            "goto_stage": goto_stage.to_dict(),
            "ap_cost": ap_cost.to_dict(),
            "goto_interlude": goto_interlude.to_dict(),
            "mission_touch": list(INTERLUDE_MISSION_TOUCH_POINT),
            "return_touch": list(INTERLUDE_RETURN_TOUCH_POINT),
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
    def _clear_roi(center: list[int]) -> tuple[int, int, int, int] | None:
        left = round(center[0] - 80 * FREE_QUEST_LAYOUT_SCALE)
        top = round(center[1] + 75 * FREE_QUEST_LAYOUT_SCALE)
        right = round(center[0] + 80 * FREE_QUEST_LAYOUT_SCALE)
        bottom = round(center[1] + 125 * FREE_QUEST_LAYOUT_SCALE)
        if left < 0 or top < 0 or right >= 1280 or bottom >= 720:
            return None
        return left, top, right - left + 1, bottom - top + 1
