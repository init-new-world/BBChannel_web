from __future__ import annotations

from typing import Any

from webapp.services.recognition import RecognitionService
from webapp.services.resources import ResourceService


ASSIST_FACE_SCALES = (1.0, 0.75, 2 / 3, 0.5)
ASSIST_EQUIP_SCALES = (1.0, 0.75, 2 / 3, 0.5)


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
        server: str = "CH",
        threshold: float = 0.85,
    ) -> dict[str, Any]:
        canonical_name = assist.get("servant_canonical_name")
        templates = self._servant_templates(canonical_name)
        equip_templates = self._equip_templates(assist.get("equip_names"))
        equip_matches = {
            equip_name: [
                match
                for template_path in template_paths
                for match in self._recognition.match_template_all(
                    screenshot,
                    template_path,
                    threshold=threshold,
                    scales=ASSIST_EQUIP_SCALES,
                    max_results=20,
                )
            ]
            for equip_name, template_paths in equip_templates.items()
        }
        limit_break_matches = (
            self._recognition.match_template_all(
                screenshot,
                "assist/满破标记.png",
                threshold=threshold,
                scales=ASSIST_EQUIP_SCALES,
                max_results=20,
            )
            if assist.get("full_limit_break")
            else []
        )
        friend_matches = (
            self._recognition.match_template_all(
                screenshot,
                f"battle/{server.upper()}/is_friend.png",
                threshold=threshold,
                scales=ASSIST_EQUIP_SCALES,
                max_results=20,
            )
            if assist.get("friend_only")
            else []
        )
        required_np_level = assist.get("np_level")
        np_level_matches = (
            self._np_level_matches(screenshot, server, threshold)
            if isinstance(required_np_level, int)
            and not isinstance(required_np_level, bool)
            and required_np_level > 1
            else []
        )
        required_skill_levels = assist.get("skill_levels")
        required_level_ten_count = (
            sum(level == 10 for level in required_skill_levels)
            if isinstance(required_skill_levels, list)
            and all(level in {0, 10} for level in required_skill_levels)
            else 0
        )
        level_ten_matches = (
            self._recognition.match_template_all(
                screenshot,
                "assist/full_skill/10.png",
                threshold=threshold,
                scales=ASSIST_EQUIP_SCALES,
                max_results=50,
            )
            if required_level_ten_count
            else []
        )
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
                "checks": {},
            }
            if any(self._overlaps(candidate["bounds"], found["bounds"]) for found in candidates):
                continue
            if equip_templates:
                equip_match = self._candidate_equip_match(candidate["anchor"], equip_matches)
                if equip_match is None:
                    continue
                equip_name, match = equip_match
                candidate["checks"] = {
                    "equip_name": equip_name,
                    "equip_template": match.template_path,
                    "equip_confidence": match.confidence,
                }
            if assist.get("full_limit_break"):
                limit_break_match = self._candidate_limit_break_match(
                    candidate["anchor"],
                    limit_break_matches,
                )
                if limit_break_match is None:
                    continue
                candidate["checks"].update(
                    {
                        "full_limit_break": True,
                        "limit_break_template": limit_break_match.template_path,
                        "limit_break_confidence": limit_break_match.confidence,
                    }
                )
            if assist.get("friend_only"):
                friend_match = self._candidate_friend_match(
                    candidate["anchor"],
                    friend_matches,
                )
                if friend_match is None:
                    continue
                candidate["checks"].update(
                    {
                        "friend": True,
                        "friend_template": friend_match.template_path,
                        "friend_confidence": friend_match.confidence,
                    }
                )
            if np_level_matches:
                np_level_match = self._candidate_np_level_match(
                    candidate["anchor"],
                    np_level_matches,
                )
                if np_level_match is None or np_level_match[0] < required_np_level:
                    continue
                np_level, match = np_level_match
                candidate["checks"].update(
                    {
                        "np_level": np_level,
                        "np_level_template": match.template_path,
                        "np_level_confidence": match.confidence,
                    }
                )
            if required_level_ten_count:
                skill_matches = self._candidate_skill_matches(
                    candidate["anchor"],
                    level_ten_matches,
                )
                if len(skill_matches) < required_level_ten_count:
                    continue
                skill_matches = skill_matches[:required_level_ten_count]
                candidate["checks"].update(
                    {
                        "skill_levels": [10] * required_level_ten_count,
                        "skill_templates": [
                            match.template_path for match in skill_matches
                        ],
                        "skill_confidences": [
                            match.confidence for match in skill_matches
                        ],
                    }
                )
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

    def _equip_templates(self, equip_names: Any) -> dict[str, list[str]]:
        if not isinstance(equip_names, list):
            return {}
        entries = self._resources.template_index(
            prefix="assist/assist_equip",
            limit=1000,
        )["entries"]
        templates: dict[str, list[str]] = {}
        for equip_name in equip_names:
            if not isinstance(equip_name, str) or not equip_name:
                continue
            templates[equip_name] = [
                str(entry["path"])
                for entry in entries
                if str(entry["path"]).rsplit("/", 1)[-1].rsplit(".", 1)[0]
                == equip_name
            ]
        return templates

    def _np_level_matches(
        self,
        screenshot: bytes,
        server: str,
        threshold: float,
    ) -> list[tuple[int, Any]]:
        entries = self._resources.template_index(
            prefix=f"assist/np_level_{server.upper()}",
            limit=100,
        )["entries"]
        matches: list[tuple[int, Any]] = []
        for entry in entries:
            template_path = str(entry["path"])
            stem = template_path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
            if not stem.startswith("level") or not stem[5:].isdigit():
                continue
            level = int(stem[5:])
            matches.extend(
                (level, match)
                for match in self._recognition.match_template_all(
                    screenshot,
                    template_path,
                    threshold=threshold,
                    scales=ASSIST_EQUIP_SCALES,
                    max_results=20,
                )
            )
        return matches

    @staticmethod
    def _candidate_equip_match(anchor: list[int], equip_matches: dict[str, list[Any]]):
        anchor_x, anchor_y = anchor
        matches = [
            (equip_name, match)
            for equip_name, named_matches in equip_matches.items()
            for match in named_matches
            if anchor_x - 100 <= match.center[0] <= anchor_x + 70
            and anchor_y + 25 <= match.center[1] <= anchor_y + 110
        ]
        if not matches:
            return None
        return max(matches, key=lambda item: item[1].confidence)

    @staticmethod
    def _candidate_limit_break_match(anchor: list[int], matches: list[Any]):
        anchor_x, anchor_y = anchor
        nearby = [
            match
            for match in matches
            if anchor_x + 40 <= match.center[0] <= anchor_x + 90
            and anchor_y + 45 <= match.center[1] <= anchor_y + 110
        ]
        if not nearby:
            return None
        return max(nearby, key=lambda match: match.confidence)

    @staticmethod
    def _candidate_friend_match(anchor: list[int], matches: list[Any]):
        anchor_y = anchor[1]
        nearby = [
            match
            for match in matches
            if anchor_y + 20 <= match.center[1] <= anchor_y + 100
        ]
        if not nearby:
            return None
        return max(nearby, key=lambda match: match.confidence)

    @staticmethod
    def _candidate_np_level_match(
        anchor: list[int],
        matches: list[tuple[int, Any]],
    ) -> tuple[int, Any] | None:
        anchor_x, anchor_y = anchor
        nearby = [
            (level, match)
            for level, match in matches
            if match.center[0] >= anchor_x + 100
            and anchor_y + 10 <= match.center[1] <= anchor_y + 110
        ]
        if not nearby:
            return None
        return max(nearby, key=lambda item: item[1].confidence)

    @staticmethod
    def _candidate_skill_matches(anchor: list[int], matches: list[Any]) -> list[Any]:
        anchor_x, anchor_y = anchor
        return sorted(
            (
                match
                for match in matches
                if match.center[0] >= anchor_x + 80
                and anchor_y + 10 <= match.center[1] <= anchor_y + 110
            ),
            key=lambda match: match.center[0],
        )

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
