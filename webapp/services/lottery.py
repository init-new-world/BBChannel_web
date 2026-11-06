from __future__ import annotations

from typing import Any

from webapp.services.recognition import RecognitionService
from webapp.services.resources import ResourceService

try:
    import cv2
except ImportError:  # pragma: no cover - handled as unknown recognition state
    cv2 = None  # type: ignore[assignment]

try:
    import numpy as np
except ImportError:  # pragma: no cover - handled as unknown recognition state
    np = None  # type: ignore[assignment]


LOTTERY_SCALES = (1.0, 0.75, 2 / 3, 0.5)
DRAW_POINT = (413, 435)
RESET_POINT = (1137, 243)
CONFIRM_RESET_POINT = (860, 563)
CLOSE_DIALOG_POINT = (640, 557)
GIFTBOX_SCROLLBAR_ROI = (913, 0, 47, 720)
GIFTBOX_STACK_ICON_ROI = (100, 167, 107, 553)
RECEIVE_SELECTED_POINT = (1149, 372)

_GIFTBOX_STACK_TEMPLATE_FILES = {
    3: "df0.png",
    4: "df1.png",
    5: "df2.png",
}

_DIGIT_PART_SLICES = {
    0: (slice(None, 20), slice(None)),
    1: (slice(17, None), slice(None)),
    2: (slice(17, None), slice(None)),
    3: (slice(None), slice(None, 9)),
    4: (slice(17, None), slice(None)),
    5: (slice(None), slice(None, 11)),
    6: (slice(None, 17), slice(None)),
    7: (slice(None, 13), slice(None)),
    8: (slice(None, 19), slice(None)),
    9: (slice(14, None), slice(None)),
}


def normalize_giftbox_max_counts(value: object) -> dict[int, int | None]:
    result: dict[int, int | None] = {3: None, 4: None, 5: None}
    if value is None:
        return result
    if not isinstance(value, dict):
        raise ValueError(
            "max_stack_counts must be an object mapping 3, 4, or 5 to positive integers."
        )
    for raw_key, raw_limit in value.items():
        if isinstance(raw_key, bool):
            raise ValueError("max_stack_counts keys must be 3, 4, or 5.")
        try:
            star = int(str(raw_key).strip())
        except ValueError as exc:
            raise ValueError("max_stack_counts keys must be 3, 4, or 5.") from exc
        if star not in {3, 4, 5}:
            raise ValueError("max_stack_counts keys must be 3, 4, or 5.")
        if raw_limit is None:
            result[star] = None
            continue
        if isinstance(raw_limit, bool) or not isinstance(raw_limit, int):
            raise ValueError(
                f"max_stack_counts[{star}] must be an integer between 1 and 9999."
            )
        if not 1 <= raw_limit <= 9999:
            raise ValueError(
                f"max_stack_counts[{star}] must be an integer between 1 and 9999."
            )
        result[star] = raw_limit
    return result


def _normalize_giftbox_stars(value: object) -> list[int]:
    if (
        not isinstance(value, (list, tuple))
        or not value
        or any(
            isinstance(star, bool)
            or not isinstance(star, int)
            or star not in {3, 4, 5}
            for star in value
        )
    ):
        raise ValueError("stars must be a non-empty list containing 3, 4, or 5.")
    return sorted(set(value))


_STATE_SPECS = (
    (
        "giftbox_full",
        "giftbox_full.png",
        "blocked",
        "giftbox_full",
        None,
        (793, 533, 140, 60),
        None,
    ),
    (
        "confirm_reset",
        "do_reset.png",
        "actionable",
        None,
        "confirm_reset",
        (787, 533, 100, 60),
        CONFIRM_RESET_POINT,
    ),
    (
        "close_dialog",
        "close.png",
        "actionable",
        None,
        "close_dialog",
        (593, 533, 93, 60),
        CLOSE_DIALOG_POINT,
    ),
    (
        "result_close",
        "x.png",
        "actionable",
        None,
        "close_result",
        (1120, 0, 160, 80),
        None,
    ),
    (
        "pool_empty",
        "pool_empty.png",
        "complete",
        "pool_empty",
        None,
        (280, 333, 220, 114),
        None,
    ),
    (
        "reset",
        "reset.png",
        "actionable",
        None,
        "reset_pool",
        (1100, 220, 80, 47),
        RESET_POINT,
    ),
    (
        "draw_10",
        "ge.png",
        "actionable",
        None,
        "draw",
        (407, 413, 100, 67),
        DRAW_POINT,
    ),
    (
        "draw_1",
        "ge.png",
        "actionable",
        None,
        "draw",
        (267, 413, 87, 67),
        DRAW_POINT,
    ),
    (
        "drawing",
        "ge.png",
        "actionable",
        None,
        "draw",
        (380, 340, 93, 60),
        DRAW_POINT,
    ),
)

_GIFTBOX_STATE_SPECS = (
    ("giftbox_full", "giftbox_full.png", "actionable", None, (793, 533, 140, 60)),
    ("receive_confirm", "receive.png", "actionable", None, (787, 533, 100, 60)),
    (
        "inventory_full",
        "close.png",
        "blocked",
        "inventory_full",
        (593, 533, 93, 60),
    ),
    ("filter_dialog", "decide.png", "actionable", None, (767, 600, 333, 67)),
    (
        "receive_all_on",
        "receive_all_on.png",
        "actionable",
        None,
        (1047, 193, 120, 53),
    ),
    (
        "receive_all_off",
        "receive_all_off.png",
        "complete",
        "giftbox_empty",
        (1047, 193, 120, 53),
    ),
    (
        "giftbox_loaded",
        "giftbox_loaded.png",
        "actionable",
        None,
        (267, 93, 87, 40),
    ),
    ("giftbox", "in_box.png", "actionable", None, (253, 13, 80, 67)),
)

_GIFTBOX_TOGGLE_SPECS = (
    ("servant_exp_on", "servant_on.png", (487, 217, 97, 63)),
    ("servant_exp_off", "servant_off.png", (487, 217, 97, 63)),
)

_NAVIGATION_STATE_SPECS = (
    (
        "choose_pay",
        "unlimitedPool",
        "choose_pay.png",
        (600, 587, 80, 60),
    ),
    ("pay", "unlimitedPool", "pay.png", (1120, 7, 127, 66)),
    (
        "giftbox_loaded",
        "unlimitedPool",
        "giftbox_loaded.png",
        (267, 93, 87, 40),
    ),
    ("giftbox", "unlimitedPool", "in_box.png", (253, 13, 80, 67)),
    ("menu_expanded", "expball", "shop.png", (720, 547, 173, 173)),
    ("menu_available", "expball", "menu.png", (1033, 533, 247, 187)),
)

_STAR_FILTER_ROIS = {
    3: (580, 467, 33, 33),
    4: (393, 467, 33, 33),
    5: (205, 467, 34, 33),
}
_STAR_FILTER_SELECTED_BGR = (196, 112, 61)
_STAR_FILTER_DISABLED_BGR = (215, 215, 215)
_STAR_FILTER_COLOR_DISTANCE = 80


class LotteryRecognizer:
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
        server: str,
        *,
        threshold: float = 0.8,
    ) -> dict[str, Any]:
        normalized_server = server.strip().upper()
        if normalized_server not in {"CH", "CNTW", "JP"}:
            raise ValueError("server must be CH, CNTW, or JP.")
        if not 0 <= threshold <= 1:
            raise ValueError("threshold must be between 0 and 1.")

        root = f"unlimitedPool/{normalized_server}"
        page = self._resources.template_index(prefix=root, limit=100)
        available_paths = {str(entry["path"]) for entry in page["entries"]}
        available_specs = [
            (
                name,
                status,
                reason,
                action,
                roi,
                action_point,
                f"{root}/{filename}",
            )
            for name, filename, status, reason, action, roi, action_point in _STATE_SPECS
            if f"{root}/{filename}" in available_paths
        ]
        candidates = [
            {
                "template_path": template_path,
                "threshold": threshold,
                "roi": roi,
                "scales": LOTTERY_SCALES,
            }
            for (
                _name,
                _status,
                _reason,
                _action,
                roi,
                _action_point,
                template_path,
            ) in available_specs
        ]
        results = (
            self._recognition.match_templates(screenshot, candidates)
            if candidates
            else []
        )
        matches = []
        for match, spec in zip(results, available_specs, strict=True):
            if not match.matched:
                continue
            name, status, reason, action, _roi, action_point, _path = spec
            matches.append(
                {
                    "name": name,
                    "status": status,
                    "reason": reason,
                    "recommended_action": action,
                    "action_point": (
                        list(action_point) if action_point is not None else match.center
                    ),
                    **match.to_dict(),
                }
            )

        primary = matches[0] if matches else None
        return {
            "server": normalized_server,
            "state": primary["name"] if primary else "unknown",
            "status": primary["status"] if primary else "unknown",
            "reason": primary["reason"] if primary else None,
            "recommended_action": (
                primary["recommended_action"] if primary else None
            ),
            "action_point": primary["action_point"] if primary else None,
            "available_template_count": len(candidates),
            "matches": matches,
        }

    def recognize_giftbox(
        self,
        screenshot: bytes,
        server: str,
        *,
        threshold: float = 0.8,
    ) -> dict[str, Any]:
        normalized_server = server.strip().upper()
        if normalized_server not in {"CH", "CNTW", "JP"}:
            raise ValueError("server must be CH, CNTW, or JP.")
        if not 0 <= threshold <= 1:
            raise ValueError("threshold must be between 0 and 1.")

        root = f"unlimitedPool/{normalized_server}"
        page = self._resources.template_index(prefix=root, limit=100)
        available_paths = {str(entry["path"]) for entry in page["entries"]}
        available_specs = [
            (name, status, reason, roi, f"{root}/{filename}")
            for name, filename, status, reason, roi in _GIFTBOX_STATE_SPECS
            if f"{root}/{filename}" in available_paths
        ]
        available_toggles = [
            (name, roi, f"{root}/{filename}")
            for name, filename, roi in _GIFTBOX_TOGGLE_SPECS
            if f"{root}/{filename}" in available_paths
        ]
        candidates = [
            {
                "template_path": template_path,
                "threshold": threshold,
                "roi": roi,
                "scales": LOTTERY_SCALES,
            }
            for _name, _status, _reason, roi, template_path in available_specs
        ] + [
            {
                "template_path": template_path,
                "threshold": threshold,
                "roi": roi,
                "scales": LOTTERY_SCALES,
            }
            for _name, roi, template_path in available_toggles
        ]
        results = (
            self._recognition.match_templates(screenshot, candidates)
            if candidates
            else []
        )
        state_results = results[: len(available_specs)]
        toggle_results = results[len(available_specs) :]
        matches = [
            {"name": spec[0], **match.to_dict()}
            for match, spec in zip(state_results, available_specs, strict=True)
            if match.matched
        ]
        primary = next(
            (
                (spec, match)
                for spec, match in zip(available_specs, state_results, strict=True)
                if match.matched
            ),
            None,
        )
        toggle_matches = {
            spec[0]: match
            for spec, match in zip(available_toggles, toggle_results, strict=True)
            if match.matched
        }
        state = primary[0][0] if primary else "unknown"
        status = primary[0][1] if primary else "unknown"
        reason = primary[0][2] if primary else None
        servant_exp_enabled = None
        star_filters = {3: None, 4: None, 5: None}
        if state == "filter_dialog":
            if "servant_exp_on" in toggle_matches:
                servant_exp_enabled = True
            elif "servant_exp_off" in toggle_matches:
                servant_exp_enabled = False
            star_filters = self._star_filter_states(screenshot)

        receive_all_enabled = (
            True
            if state == "receive_all_on"
            else False if state == "receive_all_off" else None
        )
        return {
            "server": normalized_server,
            "state": state,
            "status": status,
            "reason": reason,
            "servant_exp_enabled": servant_exp_enabled,
            "star_filters": star_filters,
            "receive_all_enabled": receive_all_enabled,
            "available_template_count": len(candidates),
            "matches": matches,
        }

    def recognize_navigation(
        self,
        screenshot: bytes,
        server: str,
        *,
        threshold: float = 0.8,
    ) -> dict[str, Any]:
        normalized_server = server.strip().upper()
        if normalized_server not in {"CH", "CNTW", "JP"}:
            raise ValueError("server must be CH, CNTW, or JP.")
        if not 0 <= threshold <= 1:
            raise ValueError("threshold must be between 0 and 1.")

        available_by_root: dict[str, set[str]] = {}
        for resource_root in {spec[1] for spec in _NAVIGATION_STATE_SPECS}:
            root = f"{resource_root}/{normalized_server}"
            page = self._resources.template_index(prefix=root, limit=100)
            available_by_root[resource_root] = {
                str(entry["path"]) for entry in page["entries"]
            }

        available_specs = [
            (name, roi, f"{resource_root}/{normalized_server}/{filename}")
            for name, resource_root, filename, roi in _NAVIGATION_STATE_SPECS
            if f"{resource_root}/{normalized_server}/{filename}"
            in available_by_root[resource_root]
        ]
        candidates = [
            {
                "template_path": template_path,
                "threshold": threshold,
                "roi": roi,
                "scales": LOTTERY_SCALES,
            }
            for _name, roi, template_path in available_specs
        ]
        results = (
            self._recognition.match_templates(screenshot, candidates)
            if candidates
            else []
        )
        matches = [
            {"name": name, **match.to_dict()}
            for match, (name, _roi, _path) in zip(
                results,
                available_specs,
                strict=True,
            )
            if match.matched
        ]
        primary = matches[0] if matches else None
        return {
            "server": normalized_server,
            "state": primary["name"] if primary else "unknown",
            "status": "actionable" if primary else "unknown",
            "reason": None,
            "available_template_count": len(candidates),
            "matches": matches,
        }

    def recognize_giftbox_stacks(
        self,
        screenshot: bytes,
        server: str,
        *,
        stars: list[int] | tuple[int, ...] = (3, 4, 5),
        max_counts: dict[int | str, int | None] | None = None,
        threshold: float = 0.7,
    ) -> dict[str, Any]:
        normalized_server = server.strip().upper()
        if normalized_server not in {"CH", "CNTW", "JP"}:
            raise ValueError("server must be CH, CNTW, or JP.")
        if not 0 <= threshold <= 1:
            raise ValueError("threshold must be between 0 and 1.")
        normalized_stars = _normalize_giftbox_stars(stars)
        normalized_max_counts = normalize_giftbox_max_counts(max_counts)
        has_active_max_counts = any(
            limit is not None for limit in normalized_max_counts.values()
        )

        root = f"unlimitedPool/{normalized_server}"
        page = self._resources.template_index(prefix=root, limit=200)
        available_paths = {str(entry["path"]) for entry in page["entries"]}

        default_scrollbar = {
            "matched": False,
            "confidence": 0.0,
            "center": None,
            "at_bottom": False,
        }
        if cv2 is None or np is None:
            return {
                "server": normalized_server,
                "stars": normalized_stars,
                "max_counts": normalized_max_counts,
                "scrollbar": default_scrollbar,
                "stack_count": 0,
                "stacks": [],
                "selectable_count": 0,
                "touch_points": [],
                "receive_selected_point": list(RECEIVE_SELECTED_POINT),
            }

        image = cv2.imdecode(
            np.frombuffer(screenshot, dtype=np.uint8),
            cv2.IMREAD_COLOR,
        )
        if image is None:
            return {
                "server": normalized_server,
                "stars": normalized_stars,
                "max_counts": normalized_max_counts,
                "scrollbar": default_scrollbar,
                "stack_count": 0,
                "stacks": [],
                "selectable_count": 0,
                "touch_points": [],
                "receive_selected_point": list(RECEIVE_SELECTED_POINT),
            }

        height, width = image.shape[:2]
        scale = min(width / 1920.0, height / 1080.0)
        dy = round((height - 1080.0 * scale) / 2.0)

        scrollbar = self._recognize_giftbox_scrollbar(
            image,
            root,
            available_paths,
            scale=scale,
            dy=dy,
            threshold=min(threshold, 0.8),
        )
        raw_stacks = self._find_giftbox_stack_icons(
            image,
            root,
            available_paths,
            stars=normalized_stars,
            scale=scale,
            dy=dy,
            threshold=threshold,
        )
        digit_templates = self._load_digit_templates(root, available_paths)
        chosen_template = self._load_template_bgr(
            f"{root}/chosen.png",
            available_paths,
        )
        unchosen_template = self._load_template_bgr(
            f"{root}/unchosen.png",
            available_paths,
        )

        stacks: list[dict[str, Any]] = []
        touch_points: list[list[int]] = []
        for item in raw_stacks:
            star = int(item["star"])
            center = item["center"]
            count, digits, more_than_1000 = self._recognize_stack_count(
                image,
                center,
                normalized_server,
                scale=scale,
                digit_templates=digit_templates,
            )
            selected, selection_flag = self._recognize_stack_selection(
                image,
                center,
                scale=scale,
                dy=dy,
                chosen_template=chosen_template,
                unchosen_template=unchosen_template,
            )
            touch_point = [
                round(center[0] + 1045.0 * scale),
                round(center[1]),
            ]
            max_count = normalized_max_counts.get(star)
            if has_active_max_counts:
                eligible = bool(max_count is not None and count < max_count)
            else:
                eligible = bool(count < 10000)
            should_select = bool(eligible and selected is False)
            if should_select:
                touch_points.append(touch_point)
            stacks.append(
                {
                    "star": star,
                    "count": count,
                    "digits": digits,
                    "more_than_1000": more_than_1000,
                    "confidence": round(float(item["confidence"]), 4),
                    "center": list(center),
                    "top_left": list(item["top_left"]),
                    "size": list(item["size"]),
                    "selected": selected,
                    "selection_flag": (
                        round(float(selection_flag), 4)
                        if selection_flag is not None
                        else None
                    ),
                    "max_count": max_count,
                    "eligible": eligible,
                    "should_select": should_select,
                    "touch_point": touch_point,
                }
            )

        return {
            "server": normalized_server,
            "stars": normalized_stars,
            "max_counts": normalized_max_counts,
            "scrollbar": scrollbar,
            "stack_count": len(stacks),
            "stacks": stacks,
            "selectable_count": len(touch_points),
            "touch_points": touch_points,
            "receive_selected_point": list(RECEIVE_SELECTED_POINT),
        }

    def _load_template_bgr(
        self,
        template_path: str,
        available_paths: set[str],
    ) -> Any:
        if cv2 is None or template_path not in available_paths:
            return None
        try:
            resolved = self._resources.resolve_template(template_path)
        except Exception:
            return None
        return cv2.imread(str(resolved), cv2.IMREAD_COLOR)

    def _load_template_gray(
        self,
        template_path: str,
        available_paths: set[str],
    ) -> Any:
        if cv2 is None or template_path not in available_paths:
            return None
        try:
            resolved = self._resources.resolve_template(template_path)
        except Exception:
            return None
        return cv2.imread(str(resolved), cv2.IMREAD_GRAYSCALE)

    def _load_digit_templates(
        self,
        root: str,
        available_paths: set[str],
    ) -> dict[int, tuple[Any, Any]]:
        templates: dict[int, tuple[Any, Any]] = {}
        for digit in range(10):
            gray = self._load_template_gray(
                f"{root}/digits/{digit}.png",
                available_paths,
            )
            if gray is None:
                continue
            row_slice, col_slice = _DIGIT_PART_SLICES[digit]
            part = gray[row_slice, col_slice]
            templates[digit] = (gray, part)
        return templates

    def _recognize_giftbox_scrollbar(
        self,
        image: Any,
        root: str,
        available_paths: set[str],
        *,
        scale: float,
        dy: int,
        threshold: float,
    ) -> dict[str, Any]:
        template = self._load_template_gray(f"{root}/scrollbar.png", available_paths)
        if template is None:
            return {
                "matched": False,
                "confidence": 0.0,
                "center": None,
                "at_bottom": False,
            }
        left = max(0, round(1370.0 * scale))
        top = max(0, dy)
        right = min(image.shape[1], round(1440.0 * scale))
        bottom = min(image.shape[0], round(dy + 1080.0 * scale))
        crop = image[top:bottom, left:right]
        if crop.size == 0:
            return {
                "matched": False,
                "confidence": 0.0,
                "center": None,
                "at_bottom": False,
            }
        crop_gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        tw = max(1, round(template.shape[1] * scale))
        th = max(1, round(template.shape[0] * scale))
        if tw > crop_gray.shape[1] or th > crop_gray.shape[0]:
            return {
                "matched": False,
                "confidence": 0.0,
                "center": None,
                "at_bottom": False,
            }
        resized = cv2.resize(template, (tw, th))
        matrix = cv2.matchTemplate(crop_gray, resized, cv2.TM_CCOEFF_NORMED)
        _min_val, max_val, _min_loc, max_loc = cv2.minMaxLoc(matrix)
        confidence = float(max_val)
        if confidence < threshold:
            return {
                "matched": False,
                "confidence": round(confidence, 4),
                "center": None,
                "at_bottom": False,
            }
        center = [
            round(left + max_loc[0] + tw / 2.0),
            round(top + max_loc[1] + th / 2.0),
        ]
        at_bottom = bool((center[1] - dy) >= 1000.0 * scale)
        return {
            "matched": True,
            "confidence": round(confidence, 4),
            "center": center,
            "at_bottom": at_bottom,
        }

    def _find_giftbox_stack_icons(
        self,
        image: Any,
        root: str,
        available_paths: set[str],
        *,
        stars: list[int],
        scale: float,
        dy: int,
        threshold: float,
    ) -> list[dict[str, Any]]:
        left = max(0, round(150.0 * scale))
        top = max(0, round(dy + 250.0 * scale))
        right = min(image.shape[1], round(310.0 * scale))
        bottom = min(image.shape[0], round(dy + 1080.0 * scale))
        crop = image[top:bottom, left:right]
        if crop.size == 0:
            return []
        crop_gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        candidates: list[dict[str, Any]] = []
        for star in stars:
            filename = _GIFTBOX_STACK_TEMPLATE_FILES[star]
            template = self._load_template_gray(
                f"{root}/{filename}",
                available_paths,
            )
            if template is None:
                continue
            tw = max(1, round(template.shape[1] * scale))
            th = max(1, round(template.shape[0] * scale))
            if tw > crop_gray.shape[1] or th > crop_gray.shape[0]:
                continue
            resized = cv2.resize(template, (tw, th))
            matrix = cv2.matchTemplate(crop_gray, resized, cv2.TM_CCOEFF_NORMED).copy()
            while True:
                _min_val, max_val, _min_loc, max_loc = cv2.minMaxLoc(matrix)
                if float(max_val) < threshold:
                    break
                cx = round(left + max_loc[0] + tw / 2.0)
                cy = round(top + max_loc[1] + th / 2.0)
                if 320.0 * scale <= (cy - dy) <= 1070.0 * scale:
                    candidates.append(
                        {
                            "star": star,
                            "confidence": float(max_val),
                            "center": [cx, cy],
                            "top_left": [
                                round(left + max_loc[0]),
                                round(top + max_loc[1]),
                            ],
                            "size": [tw, th],
                        }
                    )
                x0 = max(0, round(max_loc[0] - tw / 2.0))
                y0 = max(0, round(max_loc[1] - th / 2.0))
                x1 = min(matrix.shape[1] - 1, round(max_loc[0] + tw / 2.0))
                y1 = min(matrix.shape[0] - 1, round(max_loc[1] + th / 2.0))
                cv2.rectangle(matrix, (x0, y0), (x1, y1), 0.0, -1)

        candidates.sort(key=lambda item: float(item["confidence"]), reverse=True)
        deduped: list[dict[str, Any]] = []
        min_row_gap = max(12, round(40.0 * scale))
        for item in candidates:
            if any(
                abs(item["center"][1] - existing["center"][1]) < min_row_gap
                for existing in deduped
            ):
                continue
            deduped.append(item)
        deduped.sort(key=lambda item: (item["center"][1], item["star"]))
        return deduped

    def _recognize_stack_count(
        self,
        image: Any,
        center: list[int],
        server: str,
        *,
        scale: float,
        digit_templates: dict[int, tuple[Any, Any]],
    ) -> tuple[int, list[int], bool]:
        if not digit_templates:
            return 10000, [], False
        cx, cy = center
        x1, x2 = (376, 400) if server == "CH" else (380, 404)
        thousand_box = self._crop_box(
            image,
            round(cx + x1 * scale),
            round(cy - 70.0 * scale),
            round(cx + x2 * scale),
            round(cy - 30.0 * scale),
        )
        more_than_1000 = False
        if thousand_box.size > 0:
            _, binary = cv2.threshold(thousand_box, 127, 255, cv2.THRESH_BINARY)
            if not bool(binary.all()):
                more_than_1000 = True

        digits: list[int] = []
        dx = 0
        for index in range(4):
            if server == "CH":
                if index == 1 and more_than_1000:
                    dx += 8
                crop = self._crop_box(
                    image,
                    round(cx + (302 + dx) * scale),
                    round(cy - 70.0 * scale),
                    round(cx + (338 + dx) * scale),
                    round(cy - 30.0 * scale),
                )
            elif server == "CNTW":
                if index == 1 and more_than_1000:
                    dx += 7
                crop = self._crop_box(
                    image,
                    round(cx + (310 + dx) * scale),
                    round(cy - 68.0 * scale),
                    round(cx + (346 + dx) * scale),
                    round(cy - 28.0 * scale),
                )
            else:
                if index == 1 and more_than_1000:
                    dx += 10
                crop = self._crop_box(
                    image,
                    round(cx + (300 + dx) * scale),
                    round(cy - 70.0 * scale),
                    round(cx + (336 + dx) * scale),
                    round(cy - 30.0 * scale),
                )
            digit = self._recognize_single_digit(crop, digit_templates)
            if digit is None:
                break
            if server == "CH":
                dx += 17 if digit == 1 else 24
            elif server == "CNTW":
                dx += 19
            else:
                dx += 22
            digits.append(digit)

        if not digits or digits[0] == 0:
            return 10000, digits, more_than_1000
        value = 0
        for digit in digits:
            value = value * 10 + digit
        if more_than_1000 and value < 1000:
            return 10000, digits, more_than_1000
        return value, digits, more_than_1000

    def _recognize_single_digit(
        self,
        crop: Any,
        digit_templates: dict[int, tuple[Any, Any]],
    ) -> int | None:
        if crop.size == 0:
            return None
        resized = cv2.resize(crop, (36, 40))
        resized_gray = (
            cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
            if len(resized.shape) == 3
            else resized
        )
        scored: list[tuple[int, float]] = []
        for digit, (template, _part) in digit_templates.items():
            if (
                template.shape[0] > resized_gray.shape[0]
                or template.shape[1] > resized_gray.shape[1]
            ):
                continue
            matrix = cv2.matchTemplate(
                resized_gray,
                template,
                cv2.TM_CCOEFF_NORMED,
            )
            _min_val, max_val, _min_loc, _max_loc = cv2.minMaxLoc(matrix)
            if float(max_val) >= 0.5:
                scored.append((digit, float(max_val)))
        if not scored:
            return None
        scored.sort(key=lambda item: item[1], reverse=True)
        if len(scored) == 1 or (scored[0][1] - scored[1][1]) > 0.1:
            return scored[0][0]
        first_digit = scored[0][0]
        second_digit = scored[1][0]
        first_part = digit_templates[first_digit][1]
        second_part = digit_templates[second_digit][1]
        first_part_score = float(
            cv2.minMaxLoc(
                cv2.matchTemplate(
                    resized_gray,
                    first_part,
                    cv2.TM_CCOEFF_NORMED,
                )
            )[1]
        )
        second_part_score = float(
            cv2.minMaxLoc(
                cv2.matchTemplate(
                    resized_gray,
                    second_part,
                    cv2.TM_CCOEFF_NORMED,
                )
            )[1]
        )
        return second_digit if second_part_score > first_part_score else first_digit

    def _recognize_stack_selection(
        self,
        image: Any,
        center: list[int],
        *,
        scale: float,
        dy: int,
        chosen_template: Any,
        unchosen_template: Any,
    ) -> tuple[bool | None, float | None]:
        if chosen_template is None or unchosen_template is None:
            return None, None
        cx, cy = center
        chosen_crop = chosen_template
        unchosen_crop = unchosen_template
        max_bottom = 1080.0 * scale + dy
        if cy + 85.0 * scale > max_bottom:
            crop_height = min(85, round((max_bottom - cy) / scale))
            if crop_height <= 0:
                return None, None
            chosen_crop = chosen_template[:crop_height, :90]
            unchosen_crop = unchosen_template[:crop_height, :90]
        target = self._crop_box(
            image,
            round(cx + 1000.0 * scale),
            round(cy),
            round(cx + 1090.0 * scale),
            round(min(round(cy + 85.0 * scale), max_bottom)),
        )
        if target.size == 0:
            return None, None
        th, tw = target.shape[:2]
        if th <= 0 or tw <= 0:
            return None, None
        unchosen_resized = cv2.resize(unchosen_crop, (tw, th)).astype(np.int16)
        chosen_resized = cv2.resize(chosen_crop, (tw, th)).astype(np.int16)
        target_i16 = target[:, :, :3].astype(np.int16)
        norm_unchosen = float(np.linalg.norm(unchosen_resized - target_i16))
        norm_chosen = float(np.linalg.norm(chosen_resized - target_i16))
        if norm_unchosen <= 0:
            return False, 0.0
        flag = (norm_unchosen - norm_chosen) / norm_unchosen
        return bool(flag >= 0.1), flag

    @staticmethod
    def _crop_box(
        image: Any,
        left: int,
        top: int,
        right: int,
        bottom: int,
    ) -> Any:
        x0 = max(0, left)
        y0 = max(0, top)
        x1 = min(image.shape[1], right)
        y1 = min(image.shape[0], bottom)
        if x1 <= x0 or y1 <= y0:
            return image[0:0, 0:0]
        return image[y0:y1, x0:x1]

    def _star_filter_states(self, screenshot: bytes) -> dict[int, bool | None]:
        unknown = {3: None, 4: None, 5: None}
        if cv2 is None or np is None:
            return unknown
        image = cv2.imdecode(
            np.frombuffer(screenshot, dtype=np.uint8),
            cv2.IMREAD_COLOR,
        )
        if image is None:
            return unknown

        selected_color = np.asarray(_STAR_FILTER_SELECTED_BGR, dtype=np.float32)
        disabled_color = np.asarray(_STAR_FILTER_DISABLED_BGR, dtype=np.float32)
        states: dict[int, bool | None] = {}
        for star, (left, top, width, height) in _STAR_FILTER_ROIS.items():
            crop = image[top : top + height, left : left + width]
            if crop.size == 0:
                states[star] = None
                continue
            pixels = crop.astype(np.float32)
            selected_hits = int(
                np.count_nonzero(
                    np.linalg.norm(pixels - selected_color, axis=2)
                    <= _STAR_FILTER_COLOR_DISTANCE
                )
            )
            disabled_hits = int(
                np.count_nonzero(
                    np.linalg.norm(pixels - disabled_color, axis=2)
                    <= _STAR_FILTER_COLOR_DISTANCE
                )
            )
            states[star] = (
                None
                if selected_hits == disabled_hits == 0
                else selected_hits > disabled_hits
            )
        return states
