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
ASSIST_LIMIT_BREAK_SCALES = (1.25, 1.1, 1.0, 0.9, 0.75, 2 / 3, 0.5)
ASSIST_FACE_MASK_PATH = "assist/servant_face_mask.png"
FIRST_ASSIST_SELECTION_POINT = (387, 285)
GRAND_LAYOUT_SCALE = 2 / 3
NORMALIZED_FRAME_SCALE = 2 / 3
GRAND_ASSIST_MODES = {"冠位助战", "冠位助战仅礼装"}
GRAND_EQUIP_SLOT_NAMES = ("normal", "kizuna", "houshuu")
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
        grand_equip_slots = (
            self._normalize_grand_equip_slots(assist)
            if grand_layout and not only_servant
            else None
        )
        configured_tags = assist.get("tags")
        tag_image_size = (
            self._recognition.image_size(screenshot)
            if isinstance(configured_tags, list) and configured_tags and not only_equip
            else None
        )
        canonical_name = assist.get("servant_canonical_name")
        templates = [] if only_equip else self._servant_templates(canonical_name)
        frame_size: tuple[int, int] | None = None
        if callable(getattr(self._recognition, "image_size", None)):
            try:
                frame_size = self._recognition.image_size(screenshot)
            except Exception:
                frame_size = None
        face_roi = (
            (0, 140, 260, frame_size[1] - 140)
            if frame_size is not None and frame_size[0] >= 1000 and frame_size[1] >= 600
            else None
        )
        matches = [
            match
            for template_path in templates
            for match in self._recognition.match_template_all(
                screenshot,
                template_path,
                threshold=threshold,
                roi=face_roi,
                scales=ASSIST_FACE_SCALES,
                mask_path=(
                    ASSIST_FACE_MASK_PATH
                    if (self._resources.assets_dir / ASSIST_FACE_MASK_PATH).is_file()
                    else None
                ),
                max_results=20,
            )
        ]
        if not only_equip and not matches:
            return {
                "mode": mode,
                "servant_name": assist.get("servant_name"),
                "servant_canonical_name": canonical_name,
                "servant_sn": assist.get("servant_sn"),
                "templates": templates,
                "candidates": [],
                "candidate_count": 0,
            }
        configured_equip_names = self._collect_equip_names(assist, grand_equip_slots)
        has_explicit_equip_config = any(
            key in assist for key in ("equip_names", "equip_slots", "assistEquip")
        )
        equip_templates = (
            {}
            if only_servant
            else self._equip_templates(configured_equip_names)
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
        check_limit_break = (
            bool(assist.get("full_limit_break"))
            and not only_servant
            and (bool(configured_equip_names) or not has_explicit_equip_config)
        )
        limit_break_roi = (
            (300, 140, 130, frame_size[1] - 140)
            if check_limit_break
            and grand_layout
            and frame_size is not None
            and frame_size[0] >= 1000
            and frame_size[1] >= 600
            else None
        )
        limit_break_matches = (
            self._recognition.match_template_all(
                screenshot,
                "assist/满破标记.png",
                threshold=threshold,
                roi=limit_break_roi,
                scales=ASSIST_LIMIT_BREAK_SCALES,
                max_results=200,
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
        bond_equip_type = assist.get("bond_equip_type")
        skill_level_matches: list[tuple[int, Any]] | None = None
        skill_roi = (
            (740, 140, 320, frame_size[1] - 140)
            if grand_layout
            and frame_size is not None
            and frame_size[0] >= 1000
            and frame_size[1] >= 600
            else None
        )

        if grand_only_equip:
            grand_marker = self.match_grand_marker(screenshot, server)
            candidates = self._grand_equip_candidates(
                grand_marker,
                equip_matches,
                equip_slots=grand_equip_slots,
                check_limit_break=check_limit_break,
                limit_break_matches=limit_break_matches,
            )
        elif only_equip:
            candidates = self._equip_only_candidates(equip_matches)
        else:
            candidates = []
        if only_equip and check_limit_break:
            matched_candidates = []
            for candidate in candidates:
                if candidate["checks"].get("full_limit_break"):
                    matched_candidates.append(candidate)
                    continue
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
            if grand_layout and grand_equip_slots is not None:
                grand_equip_result = self._candidate_grand_equip_matches(
                    candidate["anchor"],
                    grand_equip_slots,
                    equip_matches,
                    check_limit_break=check_limit_break,
                    limit_break_matches=limit_break_matches,
                )
                if grand_equip_result is None:
                    continue
                candidate["checks"].update(grand_equip_result["checks"])
            elif equip_templates:
                equip_match = None
                if grand_layout:
                    grand_fallback = self._candidate_grand_equip_matches(
                        candidate["anchor"],
                        {
                            "normal": list(equip_templates.keys()),
                            "kizuna": [],
                            "houshuu": [],
                        },
                        equip_matches,
                        check_limit_break=check_limit_break,
                        limit_break_matches=limit_break_matches,
                    )
                    if grand_fallback is not None:
                        candidate["checks"].update(grand_fallback["checks"])
                        equip_match = (
                            grand_fallback["checks"]["equip_name"],
                            grand_fallback["primary_match"],
                        )
                if equip_match is None:
                    equip_match = self._candidate_equip_match(
                        candidate["anchor"],
                        equip_matches,
                    )
                    if equip_match is None:
                        continue
                    equip_name, match = equip_match
                    candidate["checks"] = {
                        "equip_name": equip_name,
                        "equip_template": match.template_path,
                        "equip_confidence": match.confidence,
                    }
            if check_limit_break and not candidate["checks"].get("full_limit_break"):
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
            if mode in GRAND_ASSIST_MODES and bond_equip_type in GRAND_BOND_TEMPLATES:
                bond_match = self._match_grand_bond_type(
                    screenshot,
                    candidate["anchor"],
                    bond_equip_type,
                    grand_only_equip=grand_only_equip,
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
            if normalized_skill_levels and not only_equip:
                if skill_level_matches is None:
                    skill_level_matches = self._skill_level_matches(
                        screenshot,
                        threshold,
                        server=server,
                        roi=skill_roi,
                    )
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

        if only_equip and mode in GRAND_ASSIST_MODES and bond_equip_type in GRAND_BOND_TEMPLATES:
            bond_candidates = []
            for candidate in candidates:
                bond_match = self._match_grand_bond_type(
                    screenshot,
                    candidate["anchor"],
                    bond_equip_type,
                    grand_only_equip=grand_only_equip,
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
        *,
        equip_slots: dict[str, list[str]] | None = None,
        check_limit_break: bool = False,
        limit_break_matches: list[Any] = (),
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
            anchor = [round(anchor_x), round(anchor_y)]
            if equip_slots is not None:
                slot_result = cls._candidate_grand_equip_matches(
                    anchor,
                    equip_slots,
                    equip_matches,
                    check_limit_break=check_limit_break,
                    limit_break_matches=limit_break_matches,
                )
                if slot_result is None:
                    continue
                equip_match = slot_result["primary_match"]
                checks = {
                    **slot_result["checks"],
                    "grand_marker": True,
                    "grand_marker_template": marker.template_path,
                    "grand_marker_confidence": marker.confidence,
                }
            else:
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
                checks = {
                    "equip_name": equip_name,
                    "equip_template": equip_match.template_path,
                    "equip_confidence": equip_match.confidence,
                    "grand_marker": True,
                    "grand_marker_template": marker.template_path,
                    "grand_marker_confidence": marker.confidence,
                }
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
                    "checks": checks,
                }
            )
        return candidates

    @staticmethod
    def _normalize_grand_equip_slots(
        assist: dict[str, Any],
    ) -> dict[str, list[str]] | None:
        def extract_names(entry: Any) -> list[str]:
            names: list[str] = []
            if isinstance(entry, str) and entry:
                names.append(entry)
            elif isinstance(entry, list):
                for item in entry:
                    for nested in extract_names(item):
                        if nested not in names:
                            names.append(nested)
            return names

        raw_slots = assist.get("equip_slots")
        if isinstance(raw_slots, dict):
            slots = {
                slot: extract_names(raw_slots.get(slot))
                for slot in GRAND_EQUIP_SLOT_NAMES
            }
            return slots if any(slots.values()) else None

        raw_assist_equip = assist.get("assistEquip")
        if isinstance(raw_assist_equip, list) and (
            len(raw_assist_equip) == 3
            or any(
                isinstance(item, list) or item is None
                for item in raw_assist_equip
            )
        ):
            slots = {
                slot: extract_names(
                    raw_assist_equip[index]
                    if index < len(raw_assist_equip)
                    else None
                )
                for index, slot in enumerate(GRAND_EQUIP_SLOT_NAMES)
            }
            for extra in raw_assist_equip[len(GRAND_EQUIP_SLOT_NAMES) :]:
                for name in extract_names(extra):
                    if name not in slots["normal"]:
                        slots["normal"].append(name)
            return slots if any(slots.values()) else None
        return None

    @staticmethod
    def _collect_equip_names(
        assist: dict[str, Any],
        grand_equip_slots: dict[str, list[str]] | None,
    ) -> list[str]:
        names: list[str] = []
        raw_names = assist.get("equip_names")
        if isinstance(raw_names, list):
            for name in raw_names:
                if isinstance(name, str) and name and name not in names:
                    names.append(name)
        if grand_equip_slots is not None:
            for slot in GRAND_EQUIP_SLOT_NAMES:
                for name in grand_equip_slots.get(slot, ()):
                    if isinstance(name, str) and name and name not in names:
                        names.append(name)
        return names

    @staticmethod
    def _grand_slot_roi(
        anchor: list[int],
        slot_index: int,
    ) -> tuple[int, int, int, int]:
        anchor_x, anchor_y = anchor
        return (
            round(anchor_x - 117 * 1280 / 1788),
            round(anchor_y + (-87 + 65 * slot_index) * 720 / 1006),
            round(anchor_x + 312 * 1280 / 1788),
            round(anchor_y + (-7 + 65 * slot_index) * 720 / 1006),
        )

    @classmethod
    def _candidate_grand_slot_equip_match(
        cls,
        anchor: list[int],
        slot_index: int,
        slot_equip_names: list[str],
        equip_matches: dict[str, list[Any]],
    ) -> tuple[str, Any] | None:
        roi = cls._grand_slot_roi(anchor, slot_index)
        roi_left, roi_top, roi_right, roi_bottom = roi
        matches = [
            (equip_name, match)
            for equip_name in slot_equip_names
            for match in equip_matches.get(equip_name, ())
            if cls._bounds_inside(match, roi)
            or (
                roi_left <= match.center[0] <= roi_right
                and roi_top <= match.center[1] <= roi_bottom
            )
        ]
        if not matches:
            return None
        return max(matches, key=lambda item: item[1].confidence)

    @classmethod
    def _candidate_grand_equip_matches(
        cls,
        anchor: list[int],
        equip_slots: dict[str, list[str]],
        equip_matches: dict[str, list[Any]],
        *,
        check_limit_break: bool = False,
        limit_break_matches: list[Any] = (),
    ) -> dict[str, Any] | None:
        kizuna_names = equip_slots.get("kizuna") or []
        if kizuna_names:
            kizuna_match = cls._candidate_grand_slot_equip_match(
                anchor,
                1,
                kizuna_names,
                equip_matches,
            )
            if kizuna_match is None:
                return None
            if check_limit_break:
                kizuna_lb = cls._candidate_limit_break_match(
                    anchor,
                    list(limit_break_matches),
                    grand_layout=True,
                    slot_index=1,
                )
                if kizuna_lb is None:
                    return None

        attempts = [
            (False, (("normal", 0), ("kizuna", 1), ("houshuu", 2))),
        ]
        if (equip_slots.get("normal") or []) != (equip_slots.get("houshuu") or []):
            attempts.append(
                (True, (("houshuu", 0), ("kizuna", 1), ("normal", 2))),
            )

        for swapped, slot_mapping in attempts:
            matched_slots: dict[str, dict[str, Any]] = {}
            matched_lb_slots: dict[str, dict[str, Any]] = {}
            primary_match = None
            primary_name = None
            first_lb_match = None
            failed = False

            for logical_slot, physical_slot in slot_mapping:
                required_names = equip_slots.get(logical_slot) or []
                if not required_names:
                    continue
                slot_match = cls._candidate_grand_slot_equip_match(
                    anchor,
                    physical_slot,
                    required_names,
                    equip_matches,
                )
                if slot_match is None:
                    failed = True
                    break
                equip_name, raw_match = slot_match
                slot_entry: dict[str, Any] = {
                    "equip_name": equip_name,
                    "equip_template": raw_match.template_path,
                    "equip_confidence": raw_match.confidence,
                    "physical_slot": physical_slot,
                }
                if check_limit_break:
                    lb_match = cls._candidate_limit_break_match(
                        anchor,
                        list(limit_break_matches),
                        grand_layout=True,
                        slot_index=physical_slot,
                    )
                    if lb_match is None:
                        failed = True
                        break
                    slot_entry.update(
                        {
                            "full_limit_break": True,
                            "limit_break_template": lb_match.template_path,
                            "limit_break_confidence": lb_match.confidence,
                        }
                    )
                    matched_lb_slots[logical_slot] = {
                        "physical_slot": physical_slot,
                        "template_path": lb_match.template_path,
                        "confidence": lb_match.confidence,
                    }
                    if first_lb_match is None:
                        first_lb_match = lb_match
                matched_slots[logical_slot] = slot_entry
                if primary_match is None:
                    primary_name = equip_name
                    primary_match = raw_match

            if not failed and primary_match is not None and primary_name is not None:
                checks: dict[str, Any] = {
                    "equip_name": primary_name,
                    "equip_template": primary_match.template_path,
                    "equip_confidence": primary_match.confidence,
                    "equip_slots": matched_slots,
                    "equip_slot_swapped": swapped,
                }
                if check_limit_break and first_lb_match is not None:
                    checks.update(
                        {
                            "full_limit_break": True,
                            "limit_break_template": first_lb_match.template_path,
                            "limit_break_confidence": first_lb_match.confidence,
                            "limit_break_slots": matched_lb_slots,
                        }
                    )
                return {
                    "primary_match": primary_match,
                    "checks": checks,
                }
        return None

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
        *,
        grand_only_equip: bool = True,
    ):
        anchor_x, anchor_y = anchor
        left = round(anchor_x + 122 * 1280 / 1788)
        top = round(anchor_y - 19 * 720 / 1006)
        right = round(anchor_x + 167 * 1280 / 1788)
        bottom_offset = 26 if grand_only_equip else 46
        bottom = round(anchor_y + bottom_offset * 720 / 1006)
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

    def match_sort_order(
        self,
        screenshot: bytes,
        server: str,
        *,
        threshold: float = 0.7,
    ) -> dict[str, Any]:
        paths = {
            "level": f"battle/{server.upper()}/levelorder.png",
            "load": f"battle/{server.upper()}/loadorder.png",
        }
        matches = self._recognition.match_templates(
            screenshot,
            [
                {
                    "template_path": path,
                    "threshold": threshold,
                    "roi": [1093, 93, 120, 67],
                    "scales": [NORMALIZED_FRAME_SCALE],
                }
                for path in paths.values()
            ],
        )
        matched = [match for match in matches if match.matched]
        if not matched:
            return {"matched": False, "order": None, "match": None}
        best = max(matched, key=lambda match: match.confidence)
        order = next(
            name for name, path in paths.items() if path == best.template_path
        )
        return {
            "matched": True,
            "order": order,
            "match": best,
        }

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

    def match_friend_marker(self, screenshot: bytes, server: str):
        return self._recognition.match_template(
            screenshot,
            f"battle/{server.upper()}/friend.png",
            threshold=0.8,
            roi=(1087, 157, 120, 563),
            scales=(NORMALIZED_FRAME_SCALE,),
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
        threshold: float = 0.9,
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

    def match_refresh_close(
        self,
        screenshot: bytes,
        server: str,
        *,
        threshold: float = 0.85,
    ):
        return self._recognition.match_template(
            screenshot,
            f"battle/{server.upper()}/close.png",
            threshold=threshold,
            scales=ASSIST_EQUIP_SCALES,
        )

    def match_connecting(
        self,
        screenshot: bytes,
        server: str,
        *,
        threshold: float = 0.85,
    ):
        return self._recognition.match_template(
            screenshot,
            f"battle/{server.upper()}/connecting.png",
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
        result = self._recognition.match_template(
            screenshot,
            template_path,
            threshold=threshold,
            scales=ASSIST_EQUIP_SCALES,
        )
        if result.matched:
            color_check = getattr(self._recognition, "check_color_half_mode", None)
            if callable(color_check):
                try:
                    color_available = bool(
                        color_check(screenshot, template_path, result)
                    )
                except AppError:
                    color_available = True
                if not color_available:
                    return MatchResult(
                        template_path=result.template_path,
                        matched=False,
                        confidence=result.confidence,
                        threshold=result.threshold,
                        top_left=list(result.top_left),
                        size=list(result.size),
                        center=list(result.center),
                        scale=result.scale,
                        roi=list(result.roi) if result.roi is not None else None,
                    )
        return result

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
        active_entries = self._resources.template_index(
            prefix="assist/assist_equip",
            limit=1000,
        )["entries"]
        archive_entries: list[dict[str, Any]] | None = None
        templates: dict[str, list[str]] = {}
        for equip_name in equip_names:
            if not isinstance(equip_name, str) or not equip_name:
                continue
            matched_paths = [
                str(entry["path"])
                for entry in active_entries
                if str(entry["path"]).rsplit("/", 1)[-1].rsplit(".", 1)[0]
                == equip_name
            ]
            if not matched_paths:
                if archive_entries is None:
                    archive_entries = self._resources.template_index(
                        prefix="equipmaker/assist_equip_store",
                        limit=1000,
                    )["entries"]
                matched_paths = [
                    str(entry["path"])
                    for entry in archive_entries
                    if str(entry["path"]).rsplit("/", 1)[-1].rsplit(".", 1)[0]
                    == equip_name
                ]
            templates[equip_name] = matched_paths
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
    def _identity_region_boxes(image_size: tuple[int, int], anchor_y: int) -> tuple[tuple[int, int, int, int], ...]:
        width, height = image_size
        scale = min(width / 1280, height / 720)
        top = max(0, round(anchor_y - 100 * scale))
        middle = min(height, round(anchor_y + 20 * scale))
        bottom = min(height, round(anchor_y + 110 * scale))
        # Exclude the changing skill panel and the animated right-side support rays/badge.
        return (
            (0, top, width, middle),
            (0, middle, round(760 * scale), bottom),
        )

    @classmethod
    def candidate_identity(cls, screenshot: bytes, candidate: dict[str, Any]) -> str:
        with Image.open(BytesIO(screenshot)) as source:
            image = source.convert("RGB")
        digest = hashlib.sha256(str(image.size).encode("ascii"))
        for region in cls._identity_region_boxes(image.size, candidate["anchor"][1]):
            digest.update(image.crop(region).tobytes())
        return digest.hexdigest()

    def same_candidate_row(
        self,
        before_screenshot: bytes,
        before_candidate: dict[str, Any],
        after_screenshot: bytes,
        after_candidate: dict[str, Any],
        *,
        min_correlation: float = 0.92,
    ) -> bool:
        cv, numpy = self._recognition._require_opencv()
        before = self._recognition._decode_screenshot(before_screenshot, None)
        after = self._recognition._decode_screenshot(after_screenshot, None)
        if before.shape[:2] != after.shape[:2]:
            return False
        height, width = before.shape[:2]
        before_boxes = self._identity_region_boxes((width, height), before_candidate["anchor"][1])
        after_boxes = self._identity_region_boxes((width, height), after_candidate["anchor"][1])
        for (bx1, by1, bx2, by2), (ax1, ay1, ax2, ay2) in zip(before_boxes, after_boxes, strict=True):
            patch_before = before[by1:by2, bx1:bx2]
            patch_after = after[ay1:ay2, ax1:ax2]
            common_h = min(patch_before.shape[0], patch_after.shape[0])
            common_w = min(patch_before.shape[1], patch_after.shape[1])
            if common_h <= 0 or common_w <= 0:
                return False
            patch_before = patch_before[:common_h, :common_w]
            patch_after = patch_after[:common_h, :common_w]
            if numpy.ptp(patch_before) == 0 or numpy.ptp(patch_after) == 0:
                if float(numpy.abs(patch_before.astype(numpy.float32) - patch_after.astype(numpy.float32)).max()) > 4.0:
                    return False
                continue
            correlation = float(cv.matchTemplate(patch_before, patch_after, cv.TM_CCOEFF_NORMED)[0, 0])
            if correlation < min_correlation:
                return False
        return True

    def match_skill_view(
        self, screenshot: bytes, server: str, *, anchor: list[int] | None = None,
    ) -> dict[str, Any] | None:
        image_width, image_height = self._recognition.image_size(screenshot)
        scale = min(image_width / 1920, image_height / 1080)
        left, right = round(1230 * scale), round(1430 * scale)
        top, bottom = round(235 * scale), image_height
        if anchor is not None:
            expected_y = anchor[1] + 20 * 1080 * scale / 1006 + 44 * scale
            top = max(0, round(expected_y - 60 * scale))
            bottom = min(image_height, round(expected_y + 60 * scale))
        if top >= bottom:
            return None
        paths = {view: f"battle/{server.upper()}/{view}_skill.png" for view in ("main", "append")}
        matches = self._recognition.match_templates(screenshot, [
            {"template_path": path, "threshold": 0.8,
             "roi": [left, top, right - left, bottom - top], "scales": [scale],
             "use_alpha_mask": False}
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
        *,
        server: str = "CH",
        roi: tuple[int, int, int, int] | None = None,
    ) -> list[tuple[int, Any]]:
        matches: list[tuple[int, Any]] = []
        for level, template_path, mask_path in self._skill_level_templates(server):
            matches.extend(
                (level, match)
                for match in self._recognition.match_template_all(
                    screenshot,
                    template_path,
                    threshold=threshold,
                    roi=roi,
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
        slot_index: int = 0,
    ):
        anchor_x, anchor_y = anchor
        if grand_layout:
            slot_offset_y = round(65 * slot_index * 720 / 1006)
            left, right = anchor_x + 190, anchor_x + 260
            top, bottom = anchor_y - 50 + slot_offset_y, anchor_y + 20 + slot_offset_y
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
