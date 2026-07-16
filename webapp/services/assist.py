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
        required_servant_level = assist.get("servant_level")
        check_servant_level = (
            isinstance(required_servant_level, int)
            and not isinstance(required_servant_level, bool)
            and required_servant_level > 1
        )
        servant_level_matches = (
            self._servant_level_digit_matches(screenshot, server, threshold)
            if check_servant_level
            else []
        )
        required_skill_levels = assist.get("skill_levels")
        normalized_skill_levels = (
            required_skill_levels[:3]
            if isinstance(required_skill_levels, list)
            and len(required_skill_levels) >= 3
            and all(
                isinstance(level, int) and not isinstance(level, bool)
                for level in required_skill_levels[:3]
            )
            and any(level > 0 for level in required_skill_levels[:3])
            else []
        )
        skill_level_matches = (
            self._skill_level_matches(screenshot, threshold)
            if normalized_skill_levels
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
            if check_servant_level:
                servant_level = self._candidate_servant_level(
                    candidate["bounds"],
                    servant_level_matches,
                )
                if (
                    servant_level is None
                    or servant_level["level"] > servant_level["cap"]
                    or servant_level["level"] < required_servant_level
                ):
                    continue
                candidate["checks"].update(
                    {
                        "servant_level": servant_level["level"],
                        "servant_level_cap": servant_level["cap"],
                        "servant_level_templates": [
                            match.template_path for _, match in servant_level["matches"]
                        ],
                        "servant_level_confidences": [
                            match.confidence for _, match in servant_level["matches"]
                        ],
                    }
                )
            if normalized_skill_levels:
                recognized_skills = self._candidate_skill_levels(
                    candidate["anchor"],
                    skill_level_matches,
                )
                if len(recognized_skills) < len(normalized_skill_levels):
                    continue
                recognized_skills = recognized_skills[: len(normalized_skill_levels)]
                if any(
                    actual_level < required_level
                    for (actual_level, _), required_level in zip(
                        recognized_skills,
                        normalized_skill_levels,
                        strict=True,
                    )
                ):
                    continue
                candidate["checks"].update(
                    {
                        "skill_levels": [level for level, _ in recognized_skills],
                        "skill_templates": [
                            match.template_path for _, match in recognized_skills
                        ],
                        "skill_confidences": [
                            match.confidence for _, match in recognized_skills
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

    def match_refresh_button(
        self,
        screenshot: bytes,
        server: str,
        *,
        threshold: float = 0.85,
    ):
        return self._recognition.match_template(
            screenshot,
            f"battle/{server.upper()}/listupdatebtn.png",
            threshold=threshold,
            scales=ASSIST_EQUIP_SCALES,
        )

    def match_recommended_header(
        self,
        screenshot: bytes,
        server: str,
        *,
        threshold: float = 0.85,
    ):
        return self._recognition.match_template(
            screenshot,
            f"battle/{server.upper()}/tuijian.png",
            threshold=threshold,
            scales=ASSIST_EQUIP_SCALES,
        )

    def match_reconnect(
        self,
        screenshot: bytes,
        server: str,
        *,
        threshold: float = 0.85,
    ):
        return self._recognition.match_template(
            screenshot,
            f"battle/{server.upper()}/reconnect.png",
            threshold=threshold,
            scales=ASSIST_EQUIP_SCALES,
        )

    def match_not_available(
        self,
        screenshot: bytes,
        server: str,
        *,
        threshold: float = 0.85,
    ):
        return self._recognition.match_template(
            screenshot,
            f"battle/{server.upper()}/notAvailable.png",
            threshold=threshold,
            scales=ASSIST_EQUIP_SCALES,
        )

    def match_no_assist(
        self,
        screenshot: bytes,
        server: str,
        *,
        threshold: float = 0.85,
    ):
        return self._recognition.match_template(
            screenshot,
            f"battle/{server.upper()}/no_assist.png",
            threshold=threshold,
            scales=ASSIST_EQUIP_SCALES,
        )

    def match_scrollbar(
        self,
        screenshot: bytes,
        server: str,
        *,
        threshold: float = 0.85,
    ):
        return self._recognition.match_template(
            screenshot,
            f"battle/{server.upper()}/scrollbar.png",
            threshold=threshold,
            scales=ASSIST_EQUIP_SCALES,
        )

    def match_refresh_confirmation(
        self,
        screenshot: bytes,
        server: str,
        *,
        threshold: float = 0.85,
    ):
        return self._recognition.match_template(
            screenshot,
            f"battle/{server.upper()}/listupdate.png",
            threshold=threshold,
            scales=ASSIST_EQUIP_SCALES,
        )

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

    def _skill_level_matches(
        self,
        screenshot: bytes,
        threshold: float,
    ) -> list[tuple[int, Any]]:
        entries = self._resources.template_index(
            prefix="assist/full_skill",
            limit=1000,
        )["entries"]
        paths_by_stem = {
            str(entry["path"]).rsplit("/", 1)[-1].rsplit(".", 1)[0]: str(entry["path"])
            for entry in entries
        }
        matches: list[tuple[int, Any]] = []
        for stem, template_path in paths_by_stem.items():
            if stem == "10":
                level = 10
            elif stem.startswith("num") and stem[3:].isdigit() and "mask" not in stem:
                number = int(stem[3:])
                if not 0 <= number <= 9:
                    continue
                level = 10 if number == 0 else number
            else:
                continue
            mask_path = paths_by_stem.get(f"{stem}mask")
            matches.extend(
                (level, match)
                for match in self._recognition.match_template_all(
                    screenshot,
                    template_path,
                    threshold=threshold,
                    scales=ASSIST_EQUIP_SCALES,
                    mask_path=mask_path,
                    max_results=50,
                )
            )
        return matches

    def _servant_level_digit_matches(
        self,
        screenshot: bytes,
        server: str,
        threshold: float,
    ) -> list[tuple[int, Any]]:
        prefix = "assist/full_skill"
        if server.upper() == "CNTW":
            prefix = f"{prefix}/CNTW"
        entries = self._resources.template_index(prefix=prefix, limit=1000)["entries"]
        expected_parent = prefix.count("/")
        paths_by_digit: dict[int, tuple[str, str | None]] = {}
        paths_by_stem = {
            str(entry["path"]).rsplit("/", 1)[-1].rsplit(".", 1)[0]: str(entry["path"])
            for entry in entries
            if str(entry["path"]).count("/") == expected_parent + 1
        }
        for digit in range(10):
            stem = f"num{digit}"
            template_path = paths_by_stem.get(stem)
            if template_path is None:
                continue
            paths_by_digit[digit] = (
                template_path,
                paths_by_stem.get(f"{stem}mask"),
            )

        return [
            (digit, match)
            for digit, (template_path, mask_path) in paths_by_digit.items()
            for match in self._recognition.match_template_all(
                screenshot,
                template_path,
                threshold=threshold,
                scales=ASSIST_EQUIP_SCALES,
                mask_path=mask_path,
                max_results=50,
            )
        ]

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
    def _candidate_skill_levels(
        anchor: list[int],
        matches: list[tuple[int, Any]],
    ) -> list[tuple[int, Any]]:
        anchor_x, anchor_y = anchor
        nearby = sorted(
            (
                (level, match)
                for level, match in matches
                if match.center[0] >= anchor_x + 80
                and anchor_y + 10 <= match.center[1] <= anchor_y + 110
            ),
            key=lambda item: item[1].center[0],
        )
        groups: list[list[tuple[int, Any]]] = []
        for item in nearby:
            if not groups or abs(item[1].center[0] - groups[-1][0][1].center[0]) > 20:
                groups.append([item])
            else:
                groups[-1].append(item)
        return [
            max(group, key=lambda item: item[1].confidence)
            for group in groups
        ]

    @classmethod
    def _candidate_servant_level(
        cls,
        bounds: list[int],
        matches: list[tuple[int, Any]],
    ) -> dict[str, Any] | None:
        x, y, width, height = bounds
        anchor_x = x + width / 2
        anchor_y = y + height / 2
        nearby = [
            item
            for item in matches
            if anchor_x - 0.75 * width <= item[1].center[0] <= anchor_x + 0.75 * width
            and anchor_y - 1.25 * height <= item[1].center[1] <= anchor_y - 0.35 * height
        ]
        selected: list[tuple[int, Any]] = []
        for item in sorted(nearby, key=lambda candidate: candidate[1].confidence, reverse=True):
            if any(cls._match_overlaps(item[1], found[1]) for found in selected):
                continue
            selected.append(item)
        selected.sort(key=lambda item: item[1].center[0])
        if len(selected) < 2:
            return None

        gaps = [
            selected[index + 1][1].center[0] - selected[index][1].center[0]
            for index in range(len(selected) - 1)
        ]
        split_at = max(range(len(gaps)), key=gaps.__getitem__) + 1
        digit_width = sum(item[1].size[0] for item in selected) / len(selected)
        if gaps[split_at - 1] < digit_width * 1.5:
            if len(selected) % 2:
                return None
            split_at = len(selected) // 2
        current_digits = selected[:split_at]
        cap_digits = selected[split_at:]
        if not current_digits or not cap_digits:
            return None
        return {
            "level": cls._digits_to_int(current_digits),
            "cap": cls._digits_to_int(cap_digits),
            "matches": selected,
        }

    @staticmethod
    def _digits_to_int(matches: list[tuple[int, Any]]) -> int:
        return int("".join(str(digit) for digit, _ in matches))

    @staticmethod
    def _match_overlaps(first: Any, second: Any) -> bool:
        first_bounds = [*first.top_left, *first.size]
        second_bounds = [*second.top_left, *second.size]
        return AssistRecognizer._overlaps(first_bounds, second_bounds)

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
