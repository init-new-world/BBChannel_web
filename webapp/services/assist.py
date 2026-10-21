from __future__ import annotations

import hashlib
from io import BytesIO
from typing import Any

from PIL import Image

from webapp.core.errors import AppError
from webapp.services.recognition import RecognitionService
from webapp.services.resources import ResourceService


ASSIST_FACE_SCALES = (1.25, 1.2, 1.0, 0.75, 2 / 3, 0.5)
ASSIST_EQUIP_SCALES = (1.0, 0.75, 2 / 3, 0.5)
ASSIST_LIMIT_BREAK_SCALES = (1.25, *ASSIST_EQUIP_SCALES)
ASSIST_FACE_MASK_PATH = "assist/servant_face_mask.png"
FIRST_ASSIST_SELECTION_POINT = (387, 285)
GRAND_LAYOUT_SCALE = 2 / 3
NORMALIZED_FRAME_SCALE = 2 / 3
GRAND_ASSIST_MODES = {"冠位助战", "冠位助战仅礼装"}
GRAND_BOND_TEMPLATES = {
    "初始": "UIimage/jb_normal.png",
    "NP50": "UIimage/jb_np.png",
}
ASSIST_SPECIAL_FILTERS = frozenset({"any", "arts", "buster", "quick", "u_olga", "olga"})
ASSIST_NP_COLORS = {"arts": "A", "buster": "B", "quick": "Q"}


def validate_assist_special_filter(value: Any, mode: Any) -> str:
    if not isinstance(value, str) or value not in ASSIST_SPECIAL_FILTERS:
        raise ValueError("special_filter must be any, arts, buster, quick, u_olga, or olga.")
    if value != "any" and mode in {"不识别", "仅礼装", "冠位助战仅礼装"}:
        raise ValueError("special_filter requires servant recognition.")
    return value


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
        mode = assist.get("mode") or "从者礼装"
        special_filter = validate_assist_special_filter(assist.get("special_filter", "any"), mode)
        special_image_size = (
            self._recognition.image_size(screenshot) if special_filter != "any" else None
        )
        if mode == "不识别":
            selection_x, selection_y = FIRST_ASSIST_SELECTION_POINT
            return {
                "mode": mode,
                "servant_name": assist.get("servant_name"),
                "servant_canonical_name": assist.get("servant_canonical_name"),
                "servant_sn": assist.get("servant_sn"),
                "templates": [],
                "candidates": [
                    {
                        "bounds": [67, 207, 640, 156],
                        "anchor": [selection_x - 270, selection_y + 60],
                        "confidence": 1.0,
                        "template_path": None,
                        "scale": 1.0,
                        "selection_point": [selection_x, selection_y],
                        "checks": {},
                    }
                ],
                "candidate_count": 1,
            }

        only_servant = mode == "仅从者"
        grand_only_equip = mode == "冠位助战仅礼装"
        only_equip = mode == "仅礼装" or grand_only_equip
        grand_layout = mode in GRAND_ASSIST_MODES
        configured_tags = assist.get("tags")
        tag_image_size = (
            self._recognition.image_size(screenshot)
            if isinstance(configured_tags, list) and configured_tags and not only_equip
            else None
        )
        canonical_name = assist.get("servant_canonical_name")
        templates = [] if only_equip else self._servant_templates(canonical_name)
        equip_templates = (
            {} if only_servant else self._equip_templates(assist.get("equip_names"))
        )
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
        check_limit_break = bool(assist.get("full_limit_break")) and not only_servant
        limit_break_matches = (
            self._recognition.match_template_all(
                screenshot,
                "assist/满破标记.png",
                threshold=threshold,
                scales=ASSIST_LIMIT_BREAK_SCALES,
                max_results=20,
            )
            if check_limit_break
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
            if assist.get("friend_only") and not only_equip
            else []
        )
        required_np_level = assist.get("np_level")
        check_np_level = (
            not only_equip
            and isinstance(required_np_level, int)
            and not isinstance(required_np_level, bool)
            and required_np_level > 1
        )
        np_level_matches = (
            self._np_level_matches(screenshot, server, threshold)
            if check_np_level
            else []
        )
        required_servant_level = assist.get("servant_level")
        check_servant_level = (
            not only_equip
            and isinstance(required_servant_level, int)
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
            self._skill_level_matches(screenshot, threshold, server=server)
            if normalized_skill_levels and not only_equip
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
                mask_path=(
                    ASSIST_FACE_MASK_PATH
                    if (self._resources.assets_dir / ASSIST_FACE_MASK_PATH).is_file()
                    else None
                ),
                max_results=20,
            )
        ]

        if grand_only_equip:
            grand_marker = self.match_grand_marker(screenshot, server)
            candidates = self._grand_equip_candidates(
                grand_marker,
                equip_matches,
            )
        elif only_equip:
            candidates = self._equip_only_candidates(equip_matches)
        else:
            candidates = []
        if only_equip and check_limit_break:
            matched_candidates = []
            for candidate in candidates:
                limit_break_match = self._candidate_limit_break_match(
                    candidate["anchor"],
                    limit_break_matches,
                    grand_layout=grand_layout,
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
                matched_candidates.append(candidate)
            candidates = matched_candidates
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
            if check_limit_break:
                limit_break_match = self._candidate_limit_break_match(
                    candidate["anchor"],
                    limit_break_matches,
                    grand_layout=grand_layout,
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
            if assist.get("friend_only") and not only_equip:
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
            if check_np_level:
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
            if normalized_skill_levels and not only_equip:
                recognized_skills = self._candidate_skill_levels(
                    candidate["anchor"],
                    skill_level_matches,
                    grand_layout=grand_layout,
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
            tag_matches = self._candidate_tag_matches(
                screenshot,
                candidate["anchor"],
                configured_tags,
                image_size=tag_image_size,
            )
            if tag_matches is None:
                continue
            if tag_matches:
                candidate["checks"].update(
                    {
                        "custom_tags": [
                            tag["template_name"] for tag, _match in tag_matches
                        ],
                        "custom_tag_templates": [
                            match.template_path for _tag, match in tag_matches
                        ],
                        "custom_tag_confidences": [
                            match.confidence for _tag, match in tag_matches
                        ],
                        "custom_tag_scales": [
                            match.scale for _tag, match in tag_matches
                        ],
                    }
                )
            if special_filter != "any":
                special_match = self._candidate_special_match(
                    screenshot, candidate["anchor"], special_filter,
                    server=server, grand_layout=grand_layout,
                    image_size=special_image_size, threshold=threshold,
                )
                if special_match is None:
                    continue
                candidate["checks"].update({
                    "special_filter": special_filter,
                    "special_template": special_match.template_path,
                    "special_confidence": special_match.confidence,
                })
                if special_filter in ASSIST_NP_COLORS:
                    candidate["checks"]["np_color"] = ASSIST_NP_COLORS[special_filter]
                else:
                    candidate["checks"]["olga_state"] = int(special_filter == "olga")
            candidates.append(candidate)

        bond_equip_type = assist.get("bond_equip_type")
        if mode in GRAND_ASSIST_MODES and bond_equip_type in GRAND_BOND_TEMPLATES:
            bond_candidates = []
            for candidate in candidates:
                bond_match = self._match_grand_bond_type(
                    screenshot,
                    candidate["anchor"],
                    bond_equip_type,
                )
                if not bond_match.matched:
                    continue
                candidate["checks"].update(
                    {
                        "bond_equip_type": bond_equip_type,
                        "bond_equip_template": bond_match.template_path,
                        "bond_equip_confidence": bond_match.confidence,
                    }
                )
                bond_candidates.append(candidate)
            candidates = bond_candidates

        candidates.sort(key=lambda candidate: (candidate["anchor"][1], candidate["anchor"][0]))
        return {
            "mode": mode,
            "servant_name": assist.get("servant_name"),
            "servant_canonical_name": canonical_name,
            "servant_sn": assist.get("servant_sn"),
            "templates": templates,
            "candidates": candidates,
            "candidate_count": len(candidates),
        }

    @classmethod
    def _equip_only_candidates(
        cls,
        equip_matches: dict[str, list[Any]],
    ) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []
        matches = sorted(
            (
                (equip_name, match)
                for equip_name, named_matches in equip_matches.items()
                for match in named_matches
            ),
            key=lambda item: item[1].confidence,
            reverse=True,
        )
        for equip_name, match in matches:
            scale = float(match.scale)
            center_x, center_y = match.center
            candidate = {
                "bounds": [*match.top_left, *match.size],
                "anchor": [
                    round(center_x - 15 * scale),
                    round(center_y - 45 * scale),
                ],
                "confidence": match.confidence,
                "template_path": match.template_path,
                "scale": scale,
                "selection_point": [
                    round(center_x + 255 * scale),
                    round(center_y - 105 * scale),
                ],
                "checks": {
                    "equip_name": equip_name,
                    "equip_template": match.template_path,
                    "equip_confidence": match.confidence,
                },
            }
            if any(
                cls._overlaps(candidate["bounds"], found["bounds"])
                for found in candidates
            ):
                continue
            candidates.append(candidate)
        return candidates

    @classmethod
    def _grand_equip_candidates(
        cls,
        marker: Any,
        equip_matches: dict[str, list[Any]],
    ) -> list[dict[str, Any]]:
        if not marker.matched:
            return []

        marker_x, marker_y = marker.center
        candidates: list[dict[str, Any]] = []
        for row_offset in range(-2, 3):
            row_y = marker_y + row_offset * 300 * GRAND_LAYOUT_SCALE
            if (
                row_y < 35 * GRAND_LAYOUT_SCALE
                or row_y > 1080 * GRAND_LAYOUT_SCALE
            ):
                continue
            anchor_x = marker_x - 347904 / 1788 * GRAND_LAYOUT_SCALE
            anchor_y = row_y + 107460 / 1006 * GRAND_LAYOUT_SCALE
            equip_roi = (
                round(anchor_x - 120 * 1280 / 1788),
                round(anchor_y + 50 * 720 / 1006),
                round(anchor_x + 75 * 1280 / 1788),
                round(anchor_y + 130 * 720 / 1006),
            )
            row_matches = [
                (equip_name, match)
                for equip_name, matches in equip_matches.items()
                for match in matches
                if cls._bounds_inside(match, equip_roi)
            ]
            if not row_matches:
                continue
            equip_name, equip_match = max(
                row_matches,
                key=lambda item: item[1].confidence,
            )
            anchor = [round(anchor_x), round(anchor_y)]
            candidates.append(
                {
                    "bounds": [*equip_match.top_left, *equip_match.size],
                    "anchor": anchor,
                    "confidence": equip_match.confidence,
                    "template_path": equip_match.template_path,
                    "scale": GRAND_LAYOUT_SCALE,
                    "selection_point": [
                        anchor[0],
                        round(
                            max(
                                270 * GRAND_LAYOUT_SCALE,
                                anchor_y - 60 * GRAND_LAYOUT_SCALE,
                            )
                        ),
                    ],
                    "checks": {
                        "equip_name": equip_name,
                        "equip_template": equip_match.template_path,
                        "equip_confidence": equip_match.confidence,
                        "grand_marker": True,
                        "grand_marker_template": marker.template_path,
                        "grand_marker_confidence": marker.confidence,
                    },
                }
            )
        return candidates

    @staticmethod
    def _bounds_inside(match: Any, roi: tuple[int, int, int, int]) -> bool:
        left, top = match.top_left
        width, height = match.size
        roi_left, roi_top, roi_right, roi_bottom = roi
        return (
            left >= roi_left
            and top >= roi_top
            and left + width <= roi_right
            and top + height <= roi_bottom
        )

    def _match_grand_bond_type(
        self,
        screenshot: bytes,
        anchor: list[int],
        bond_equip_type: str,
    ):
        anchor_x, anchor_y = anchor
        left = round(anchor_x + 122 * 1280 / 1788)
        top = round(anchor_y - 19 * 720 / 1006)
        right = round(anchor_x + 167 * 1280 / 1788)
        bottom = round(anchor_y + 26 * 720 / 1006)
        return self._recognition.match_template(
            screenshot,
            GRAND_BOND_TEMPLATES[bond_equip_type],
            threshold=0.5,
            roi=(left, top, right - left, bottom - top),
            scales=ASSIST_EQUIP_SCALES,
        )

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
            roi=(780, 70, 280, 120),
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

    def selected_class_index(self, screenshot: bytes, *, recommended: bool) -> int | None:
        suffix = "_s" if recommended else ""
        match = self._recognition.match_template(
            screenshot,
            f"battle/public/choosedClass{suffix}.png",
            mask_path=f"battle/public/choosedClassMask{suffix}.png",
            threshold=0.5,
            roi=(57, 80, 683, 100),
            scales=(NORMALIZED_FRAME_SCALE,),
        )
        if not match.matched or not (57 <= match.center[0] < 740 and 80 <= match.center[1] < 180):
            return None
        # Original checkChoosedClass offsets and spacing, normalized from 1920x1080.
        origin, spacing = (183, 91) if recommended else (93, 101)
        index = int((match.center[0] - origin * NORMALIZED_FRAME_SCALE) // (spacing * NORMALIZED_FRAME_SCALE))
        return index if -1 <= index <= 9 else None

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

    def match_grand_marker(
        self,
        screenshot: bytes,
        server: str,
        *,
        threshold: float = 0.7,
    ):
        return self._recognition.match_template(
            screenshot,
            f"battle/{server.upper()}/grand_gnlz.png",
            threshold=threshold,
            roi=(133, 157, 254, 563),
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

    def match_apple_close(
        self,
        screenshot: bytes,
        server: str,
        *,
        threshold: float = 0.85,
    ):
        return self._recognition.match_template(
            screenshot,
            f"battle/{server.upper()}/apple_close.png",
            threshold=threshold,
            scales=ASSIST_EQUIP_SCALES,
        )

    def match_apple_decide(
        self,
        screenshot: bytes,
        server: str,
        *,
        threshold: float = 0.85,
    ):
        return self._recognition.match_template(
            screenshot,
            f"battle/{server.upper()}/apple_decide.png",
            threshold=threshold,
            scales=ASSIST_EQUIP_SCALES,
        )

    def match_apple(
        self,
        screenshot: bytes,
        server: str,
        apple: str,
        *,
        threshold: float = 0.85,
    ):
        template_path = (
            "battle/public/blue.png"
            if apple == "blue"
            else f"battle/{server.upper()}/{apple}.png"
        )
        return self._recognition.match_template(
            screenshot,
            template_path,
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

    def _candidate_tag_matches(
        self,
        screenshot: bytes,
        anchor: list[int],
        tags: Any,
        *,
        image_size: tuple[int, int] | None,
    ) -> list[tuple[dict[str, Any], Any]] | None:
        if not isinstance(tags, list) or not tags:
            return []

        anchor_x, anchor_y = anchor
        matches: list[tuple[dict[str, Any], Any]] = []
        for tag in tags:
            if not isinstance(tag, dict):
                return None
            source_width = tag.get("source_width")
            source_height = tag.get("source_height")
            if (
                not isinstance(source_width, int)
                or isinstance(source_width, bool)
                or source_width <= 0
                or not isinstance(source_height, int)
                or isinstance(source_height, bool)
                or source_height <= 0
            ):
                return None
            source_scale = (
                source_width / 1920
                if source_width / source_height < 16 / 9
                else source_height / 1080
            )
            tag_scale = NORMALIZED_FRAME_SCALE / source_scale
            try:
                left = round(anchor_x + float(tag["left"]) * tag_scale) - 3
                top = round(
                    anchor_y
                    + float(tag["top"]) * tag_scale
                    - 25 * NORMALIZED_FRAME_SCALE
                ) - 3
                right = round(anchor_x + float(tag["right"]) * tag_scale) + 3
                bottom = round(
                    anchor_y
                    + float(tag["bottom"]) * tag_scale
                    + 25 * NORMALIZED_FRAME_SCALE
                ) + 3
                if image_size is not None:
                    image_width, image_height = image_size
                    left = max(left, 0)
                    top = max(top, 0)
                    right = min(right, image_width)
                    bottom = min(bottom, image_height)
                match = self._recognition.match_template(
                    screenshot,
                    str(tag["template_path"]),
                    threshold=float(tag["threshold"]),
                    roi=(left, top, right - left, bottom - top),
                    scales=(tag_scale,),
                )
            except (AppError, KeyError, TypeError, ValueError):
                return None
            if not match.matched:
                return None
            matches.append((tag, match))
        return matches

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

    def _candidate_special_match(
        self,
        screenshot: bytes,
        anchor: list[int],
        special_filter: str,
        *,
        server: str,
        grand_layout: bool,
        image_size: tuple[int, int],
        threshold: float,
    ):
        scale = min(image_size[0] / 1920, image_size[1] / 1080)
        width, height = 1920 * scale, 1080 * scale
        is_color = special_filter in ASSIST_NP_COLORS
        left_offset = 427 if grand_layout else 270
        right_offset = left_offset + (60 if is_color else 665)
        top_offset, bottom_offset = (20, 110) if is_color else (-30, 60)
        # Legacy checks use the portrait center adjusted by 10/20 reference pixels.
        left = round(anchor[0] + (left_offset + 10) * width / 1788)
        right = round(anchor[0] + (right_offset + 10) * width / 1788)
        top = round(anchor[1] + (top_offset + 20) * height / 1006)
        bottom = round(anchor[1] + (bottom_offset + 20) * height / 1006)
        if not (0 <= left < right <= image_size[0] and 0 <= top < bottom <= image_size[1]):
            return None
        paths = (
            {name: f"battle/public/{name}.png" for name in ASSIST_NP_COLORS}
            if is_color else {
                "u_olga": f"battle/{server.upper()}/U-Olga.png",
                "olga": f"battle/{server.upper()}/Olga.png",
            }
        )
        matches = self._recognition.match_templates(screenshot, [
            {"template_path": path, "threshold": threshold,
             "roi": [left, top, right - left, bottom - top], "scales": [scale]}
            for path in paths.values()
        ])
        matched = [match for match in matches if match.matched]
        best = max(matched, key=lambda match: match.confidence) if matched else None
        return best if best is not None and best.template_path == paths[special_filter] else None

    @staticmethod
    def candidate_identity(screenshot: bytes, candidate: dict[str, Any]) -> str:
        with Image.open(BytesIO(screenshot)) as source:
            image = source.convert("RGB")
        scale = min(image.width / 1280, image.height / 720)
        anchor_y = candidate["anchor"][1]
        top = max(0, round(anchor_y - 100 * scale))
        middle = min(image.height, round(anchor_y + 20 * scale))
        bottom = min(image.height, round(anchor_y + 110 * scale))
        # Exclude the changing skill panel, retaining player/name and row evidence.
        regions = (
            (0, top, image.width, middle),
            (0, middle, round(760 * scale), bottom),
            (round(1080 * scale), middle, image.width, bottom),
        )
        digest = hashlib.sha256(str(image.size).encode("ascii"))
        for region in regions:
            digest.update(image.crop(region).tobytes())
        return digest.hexdigest()

    def match_skill_view(
        self, screenshot: bytes, server: str, *, anchor: list[int] | None = None,
    ) -> dict[str, Any] | None:
        image_width, image_height = self._recognition.image_size(screenshot)
        scale = min(image_width / 1920, image_height / 1080)
        left, right = round(1230 * scale), round(1430 * scale)
        top, bottom = 0, image_height
        if anchor is not None:
            expected_y = anchor[1] + 20 * 1080 * scale / 1006 + 44 * scale
            top = max(0, round(expected_y - 60 * scale))
            bottom = min(image_height, round(expected_y + 60 * scale))
        if top >= bottom:
            return None
        paths = {view: f"battle/{server.upper()}/{view}_skill.png" for view in ("main", "append")}
        matches = self._recognition.match_templates(screenshot, [
            {"template_path": path, "threshold": 0.7,
             "roi": [left, top, right - left, bottom - top], "scales": [scale]}
            for path in paths.values()
        ])
        matched = [match for match in matches if match.matched]
        if not matched:
            return None
        best = max(matched, key=lambda match: match.confidence)
        return {
            "view": next(view for view, path in paths.items() if path == best.template_path),
            "match": best, "scale": scale,
        }

    def check_append_skills(
        self, screenshot: bytes, candidate: dict[str, Any], required: list[int],
        *, server: str, threshold: float = 0.85,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {"matched": False, "levels": [None] * len(required), "confidences": [None] * len(required)}
        marker = self.match_skill_view(screenshot, server, anchor=candidate["anchor"])
        if marker is None or marker["view"] != "append":
            return result
        scale = marker["scale"]
        width, height = 1920 * scale, 1080 * scale
        # Align the digit row to its recognized header after the view changes.
        anchor_y = marker["match"].center[1] - 44 * scale
        top = round(anchor_y + 84 * height / 1006) - 1
        bottom = round(anchor_y + 110 * height / 1006) + 1
        if top < 0 or bottom > height:
            return result
        spacing = 63 if server.upper() == "CNTW" else 52.5
        templates = self._skill_level_templates(server)
        for index, minimum in enumerate(required):
            if minimum == 0:
                continue
            left = round((1158 + index * spacing) * width / 1788) - 1
            right = round((1195 + index * spacing) * width / 1788) + 1
            if right > width:
                return result
            matches = self._recognition.match_templates(screenshot, [
                {"template_path": path, "mask_path": mask_path, "threshold": threshold,
                 "roi": [left, top, right - left, bottom - top],
                 "scales": [scale * 0.95, scale, scale * 1.05]}
                for _level, path, mask_path in templates
            ])
            found = [(level, match) for (level, _path, _mask), match in zip(templates, matches, strict=True) if match.matched]
            complete_ten = [item for item in found if item[1].template_path.endswith("/10.png")]
            best = max(complete_ten or found, key=lambda item: item[1].confidence) if found else None
            if best is not None:
                result["levels"][index] = best[0]
                result["confidences"][index] = best[1].confidence
            if best is None or best[0] < minimum:
                return result
        result["matched"] = True
        return result

    def _skill_level_templates(self, server: str) -> list[tuple[int, str, str | None]]:
        prefix = "assist/full_skill/CNTW" if server.upper() == "CNTW" else "assist/full_skill"
        entries = self._resources.template_index(prefix=prefix, limit=1000)["entries"]
        paths_by_stem = {
            str(entry["path"]).rsplit("/", 1)[-1].rsplit(".", 1)[0]: str(entry["path"])
            for entry in entries if str(entry["path"]).rsplit("/", 1)[0] == prefix
        }
        templates = []
        for stem, template_path in paths_by_stem.items():
            if stem == "10":
                level = 10
            elif stem.startswith("num") and stem[3:].isdigit() and 0 <= int(stem[3:]) <= 9:
                level = int(stem[3:]) or 10
            else:
                continue
            templates.append((level, template_path, paths_by_stem.get(f"{stem}mask")))
        return templates

    def _skill_level_matches(
        self,
        screenshot: bytes,
        threshold: float,
        *, server: str = "CH",
    ) -> list[tuple[int, Any]]:
        matches: list[tuple[int, Any]] = []
        for level, template_path, mask_path in self._skill_level_templates(server):
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
    def _candidate_limit_break_match(
        anchor: list[int],
        matches: list[Any],
        *,
        grand_layout: bool = False,
    ):
        anchor_x, anchor_y = anchor
        if grand_layout:
            left, right = anchor_x + 190, anchor_x + 260
            top, bottom = anchor_y - 50, anchor_y + 20
        else:
            left, right = anchor_x + 40, anchor_x + 90
            top, bottom = anchor_y + 45, anchor_y + 110
        nearby = [
            match
            for match in matches
            if left <= match.center[0] <= right
            and top <= match.center[1] <= bottom
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
        *,
        grand_layout: bool = False,
    ) -> list[tuple[int, Any]]:
        anchor_x, anchor_y = anchor
        if grand_layout:
            left, right = anchor_x + 650, anchor_x + 850
            top, bottom = anchor_y + 40, anchor_y + 100
        else:
            left, right = anchor_x + 80, float("inf")
            top, bottom = anchor_y + 10, anchor_y + 110
        nearby = sorted(
            (
                (level, match)
                for level, match in matches
                if left <= match.center[0] <= right
                and top <= match.center[1] <= bottom
            ),
            key=lambda item: item[1].center[0],
        )
        groups: list[list[tuple[int, Any]]] = []
        for item in nearby:
            if not groups or abs(item[1].center[0] - groups[-1][0][1].center[0]) > 20:
                groups.append([item])
            else:
                groups[-1].append(item)
        selected = []
        for group in groups:
            complete_ten = [
                item
                for item in group
                if str(item[1].template_path).rsplit("/", 1)[-1] == "10.png"
            ]
            selected.append(
                max(complete_ten or group, key=lambda item: item[1].confidence)
            )
        return selected

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
