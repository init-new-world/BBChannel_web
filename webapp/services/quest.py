from __future__ import annotations

from typing import Any

from webapp.core.errors import AppError, ErrorCode
from webapp.core.models import MatchResult
from webapp.services.recognition import RecognitionService


FREE_QUEST_SCALES = (1.0, 0.75, 2 / 3, 0.5)
FREE_QUEST_LIST_ROI = (600, 0, 200, 720)
FREE_QUEST_LAYOUT_SCALE = 2 / 3
MAIN_STORY_LEFT_CLOSE_ROI = (0, 0, 200, 93)
MAIN_STORY_INFINITE_ROI = (767, 87, 367, 247)
MAIN_STORY_UNAVAILABLE_ROI = (573, 533, 137, 60)
MAIN_STORY_START_RWKS_ROI = (733, 533, 207, 60)
MAIN_STORY_SKIP_TOP_ROI = (1120, 10, 147, 60)
MAIN_STORY_SKIP_BOTTOM_ROI = (1193, 573, 67, 80)
MAIN_STORY_SKIP_CONFIRM_ROI = (767, 533, 113, 60)
MAIN_STORY_SKIP_TOUCH_POINT = (1197, 40)
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
        ap_threshold: float = 0.7,
    ) -> dict[str, Any]:
        normalized_server = server.strip().upper()
        if normalized_server not in {"CH", "CNTW", "JP"}:
            raise ValueError("server must be CH, CNTW, or JP.")

        template_root = f"battle/MainStory/{normalized_server}"
        reddot_matches = self._recognition.match_template_all(
            screenshot,
            f"{template_root}/reddot.png",
            threshold=threshold,
            scales=FREE_QUEST_SCALES,
            mask_path=f"{template_root}/reddotMask.png",
            max_results=50,
        )
        next_matches = self._match_all_optional(
            screenshot,
            f"{template_root}/nextOne.png",
            threshold=threshold,
            scales=FREE_QUEST_SCALES,
            mask_path=f"{template_root}/nextOneMask.png",
            max_results=50,
        )
        ap_cost = self._match_optional(
            screenshot,
            f"battle/{normalized_server}/AP.png",
            threshold=ap_threshold,
            roi=INTERLUDE_AP_ROI,
            scales=FREE_QUEST_SCALES,
        )
        main_x = self._match_optional(
            screenshot,
            f"{template_root}/x.png",
            threshold=0.85,
            scales=FREE_QUEST_SCALES,
        )
        left_close = self._match_optional(
            screenshot,
            f"{template_root}/close.png",
            threshold=threshold,
            roi=MAIN_STORY_LEFT_CLOSE_ROI,
            scales=FREE_QUEST_SCALES,
        )
        ooku_ao = self._match_optional(
            screenshot,
            f"{template_root}/ao.png",
            threshold=0.7,
            scales=FREE_QUEST_SCALES,
        )
        infinite = self._match_optional(
            screenshot,
            f"{template_root}/infinite.png",
            threshold=threshold,
            roi=MAIN_STORY_INFINITE_ROI,
            scales=FREE_QUEST_SCALES,
        )
        quest_unavailable = self._match_optional(
            screenshot,
            f"battle/{normalized_server}/notAvailable.png",
            threshold=threshold,
            roi=MAIN_STORY_UNAVAILABLE_ROI,
            scales=FREE_QUEST_SCALES,
        )
        story_start = self._match_optional(
            screenshot,
            f"battle/{normalized_server}/rwks.png",
            threshold=threshold,
            roi=MAIN_STORY_START_RWKS_ROI,
            scales=FREE_QUEST_SCALES,
        )
        story_skip_confirm = self._match_optional(
            screenshot,
            f"battle/{normalized_server}/listupdate.png",
            threshold=threshold,
            roi=MAIN_STORY_SKIP_CONFIRM_ROI,
            scales=FREE_QUEST_SCALES,
        )
        story_skip = None
        for skip_name, skip_roi in (
            ("needSkip1", MAIN_STORY_SKIP_TOP_ROI),
            ("needSkip", MAIN_STORY_SKIP_BOTTOM_ROI),
        ):
            candidate = self._match_optional(
                screenshot,
                f"battle/{normalized_server}/{skip_name}.png",
                threshold=threshold,
                roi=skip_roi,
                scales=FREE_QUEST_SCALES,
            )
            if candidate is not None and candidate.matched:
                story_skip = candidate
                break
        ap_cost_matched = bool(ap_cost is not None and ap_cost.matched)

        candidates: list[dict[str, Any]] = []
        for match in self._distinct_matches(next_matches):
            x, y = match.center
            touch = [x, min(719, y + round(150 * match.scale))]
            panel_touch = [x, min(719, y + round(100 * match.scale))]
            if not ap_cost_matched and self._is_unsafe_map_point(touch):
                continue
            candidates.append(
                {
                    "type": "next",
                    "center": list(match.center),
                    "touch": panel_touch if ap_cost_matched else touch,
                    "map_touch": touch,
                    "panel_touch": panel_touch,
                    "confidence": match.confidence,
                    "scale": match.scale,
                }
            )
        for match in self._distinct_matches(reddot_matches):
            x, y = match.center
            offset = round(40 * match.scale)
            touch = [max(0, x - offset), min(719, y + offset)]
            if self._is_unsafe_map_point(touch):
                continue
            candidates.append(
                {
                    "type": "reddot",
                    "center": list(match.center),
                    "touch": touch,
                    "confidence": match.confidence,
                    "scale": match.scale,
                }
            )
        candidates.sort(
            key=lambda item: (
                item["center"][1],
                item["center"][0],
                0 if item.get("type") == "next" else 1,
            )
        )
        panel_candidates = [
            item for item in candidates if item.get("type") == "next"
        ]
        selected = (
            panel_candidates[0]
            if ap_cost_matched and panel_candidates
            else (candidates[0] if candidates else None)
        )
        return {
            "server": normalized_server,
            "candidate_count": len(candidates),
            "candidates": candidates,
            "selected": selected,
            "ap_cost": ap_cost.to_dict() if ap_cost is not None else None,
            "main_x": main_x.to_dict() if main_x is not None else None,
            "left_close": left_close.to_dict() if left_close is not None else None,
            "ooku_ao": ooku_ao.to_dict() if ooku_ao is not None else None,
            "infinite": infinite.to_dict() if infinite is not None else None,
            "quest_unavailable": (
                quest_unavailable.to_dict() if quest_unavailable is not None else None
            ),
            "story_start": story_start.to_dict() if story_start is not None else None,
            "story_skip": story_skip.to_dict() if story_skip is not None else None,
            "story_skip_confirm": (
                story_skip_confirm.to_dict()
                if story_skip_confirm is not None
                else None
            ),
            "story_skip_touch": list(MAIN_STORY_SKIP_TOUCH_POINT),
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

    def _match_optional(
        self,
        screenshot: bytes,
        template_path: str,
        **options: Any,
    ) -> MatchResult | None:
        if not hasattr(self._recognition, "match_template"):
            return None
        try:
            return self._recognition.match_template(
                screenshot,
                template_path,
                **options,
            )
        except AppError as exc:
            if exc.code == ErrorCode.TEMPLATE_NOT_FOUND:
                return None
            raise

    def _match_all_optional(
        self,
        screenshot: bytes,
        template_path: str,
        **options: Any,
    ) -> list[MatchResult]:
        if not hasattr(self._recognition, "match_template_all"):
            return []
        try:
            return self._recognition.match_template_all(
                screenshot,
                template_path,
                **options,
            )
        except AppError as exc:
            if exc.code == ErrorCode.TEMPLATE_NOT_FOUND:
                return []
            raise

    @staticmethod
    def _is_unsafe_map_point(point: list[int] | tuple[int, int]) -> bool:
        x, y = int(point[0]), int(point[1])
        return (
            x < round(345 * FREE_QUEST_LAYOUT_SCALE) and y > 490
        ) or y > round(830 * FREE_QUEST_LAYOUT_SCALE)

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
