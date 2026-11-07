from __future__ import annotations

from collections.abc import Sequence
from io import BytesIO
from pathlib import PurePosixPath
from typing import Any

from PIL import Image, UnidentifiedImageError

from webapp.services.recognition import RecognitionService
from webapp.services.resources import ResourceService


_STATE_SPECS = (
    ("noSucai", "enhancement", "blocked", "materials_exhausted", None),
    ("no_servant", "enhancement", "blocked", "no_matching_target", None),
    ("callfree", "summon", "actionable", None, "summon_free_ten"),
    ("call10", "summon", "actionable", None, "summon_ten"),
    ("again10", "summon", "actionable", None, "summon_again"),
    ("again10_1", "summon", "actionable", None, "summon_again"),
    ("again10_0", "summon", "observed", None, None),
    ("boxfull", "summon", "actionable", None, "handle_full_box"),
    ("decide", "confirmation", "actionable", None, "confirm_summon"),
    ("bianhuan", "summon", "observed", None, None),
    ("close", "summon", "actionable", None, "close_summon_result"),
    ("autoSell", "sell", "actionable", None, "open_auto_sell"),
    ("destroy", "sell", "actionable", None, "execute_sell"),
    ("gotoqhcz", "navigation", "actionable", None, "open_enhancement"),
    ("store_full", "storage", "blocked", "storage_full", None),
    ("zxStore", "storage", "actionable", None, "execute_storage"),
    ("storeAll", "storage", "actionable", None, "select_all"),
    ("jd", "selection", "actionable", None, "submit_selection"),
    ("ljbhclose", "confirmation", "actionable", None, "close_result"),
    ("qh_back", "navigation", "actionable", None, "return_from_enhancement"),
    ("back", "navigation", "actionable", None, "back"),
    ("qpfull", "confirmation", "observed", None, None),
    ("friendpointcall", "summon", "observed", None, None),
    ("in_store", "storage", "observed", None, None),
    ("feedjd", "enhancement", "actionable", None, "confirm_auto_select"),
    ("cssd", "enhancement", "actionable", None, "configure_auto_select"),
    ("doubleEXP", "enhancement", "observed", None, None),
    ("sure", "confirmation", "actionable", None, "confirm_dialog"),
    ("menu", "navigation", "observed", None, None),
    ("shop", "navigation", "observed", None, None),
    ("qhjd2", "confirmation", "actionable", None, "confirm_enhancement"),
    ("qhjd", "enhancement", "actionable", None, "confirm_material_selection"),
    ("sbzl", "enhancement", "actionable", None, "ascend_limit"),
    ("ljzl", "enhancement", "actionable", None, "grail_limit"),
    ("qdjqh", "enhancement", "actionable", None, "confirm_ascension"),
    ("slot", "enhancement", "actionable", None, "open_material_slots"),
    ("help", "enhancement", "actionable", None, "select_materials"),
    ("exlevel", "enhancement", "actionable", None, "select_base"),
    ("xzdx", "selection", "actionable", None, "select_target_card"),
    ("tysd", "selection", "actionable", None, "select_material_card"),
    ("no_wenzhang", "sell", "observed", "no_command_codes", None),
    ("no_wenzhang_1", "sell", "observed", "no_command_codes", None),
    ("fmwz_0", "sell", "actionable", None, "open_command_code_sell"),
    ("fmwz_1", "sell", "observed", None, None),
)
_SCALES = (1.0, 0.75, 2 / 3, 0.5)
_SERVANT_LEVEL_DIGIT_SCALES = (2 / 3, 0.5)
_SERVANT_LEVEL_DIGITS = tuple(range(10))
_SERVANT_LEVEL_LEFT_ROIS = tuple(
    (
        round((683 + 33 * index) * 2 / 3),
        round(680 * 2 / 3),
        round((723 + 33 * index) * 2 / 3) - round((683 + 33 * index) * 2 / 3),
        round(745 * 2 / 3) - round(680 * 2 / 3),
    )
    for index in range(2)
)
_SERVANT_LEVEL_RIGHT_ROIS = tuple(
    (
        round((782 + 33 * index) * 2 / 3),
        round(680 * 2 / 3),
        round((822 + 33 * index) * 2 / 3) - round((782 + 33 * index) * 2 / 3),
        round(745 * 2 / 3) - round(680 * 2 / 3),
    )
    for index in range(3)
)
_STORAGE_STARS = (3, 4, 5)
_FP_GOLD_SERVANTS = ("lily", "habe", "hakuno_0", "hakuno_1")
_SERVANT_FRAME_SPECS = (
    ("bronze", "1-2", False, (145, 128, 98)),
    ("silver", "3", False, (181, 181, 181)),
    ("gold_locked", "4-5", True, (120, 97, 18)),
    ("gold_unlocked", "4-5", False, (226, 181, 34)),
)
_STORAGE_CARD_ROIS = tuple(
    (
        round((112 + column * 200) * 2 / 3),
        round((271 + row * 213) * 2 / 3),
        round((297 + column * 200) * 2 / 3)
        - round((112 + column * 200) * 2 / 3),
        round((472 + row * 213) * 2 / 3)
        - round((271 + row * 213) * 2 / 3),
    )
    for row in range(3)
    for column in range(7)
)
_COMMAND_CODE_CARD_ROIS = tuple(
    (
        round((117 + column * 200) * 2 / 3),
        round((276 + row * 213) * 2 / 3),
        round((292 + column * 200) * 2 / 3)
        - round((117 + column * 200) * 2 / 3),
        round((467 + row * 213) * 2 / 3)
        - round((276 + row * 213) * 2 / 3),
    )
    for row in range(3)
    for column in range(7)
)
_NO_COMMAND_CODE_ROI = (300, 400, 233, 67)
_FIRST_CARD_LOCKER_ROI = (60, 220, 33, 40)
_CE_BOMB_CARD_ROIS = tuple(
    (
        round((90 + column * 200) * 2 / 3),
        round((275 + row * 213) * 2 / 3),
        round((296 + column * 200) * 2 / 3)
        - round((90 + column * 200) * 2 / 3),
        round((486 + row * 213) * 2 / 3)
        - round((275 + row * 213) * 2 / 3),
    )
    for row in range(3)
    for column in range(7)
)
_CE_BOMB_LOCK_ROIS = tuple(
    (
        round((90 + column * 200) * 2 / 3),
        round((275 + row * 213 + 60) * 2 / 3),
        round((90 + column * 200 + 50) * 2 / 3)
        - round((90 + column * 200) * 2 / 3),
        round((275 + row * 213 + 120) * 2 / 3)
        - round((275 + row * 213 + 60) * 2 / 3),
    )
    for row in range(3)
    for column in range(7)
)
_CE_BOMB_MARK_ROIS = tuple(
    (
        round((90 + column * 200) * 2 / 3),
        round((275 + row * 213 + 120) * 2 / 3),
        round((90 + column * 200 + 50) * 2 / 3)
        - round((90 + column * 200) * 2 / 3),
        round((275 + row * 213 + 170) * 2 / 3)
        - round((275 + row * 213 + 120) * 2 / 3),
    )
    for row in range(3)
    for column in range(7)
)
_CE_FULL_LV_RGB = (60, 54, 41)
_CE_NON_FULL_LV_RGB = (147, 130, 100)
_SERVANT_TARGET_ROI = (60, 173, 953, 547)
_SERVANT_SCROLL_END_ROI = (993, 675, 40, 26)

_NAVIGATION_STATE_SPECS = (
    ("summon_page", "friendpointcall.png", (507, 333, 263, 133)),
    ("sell_page", "ljbh.png", (673, 93, 133, 67)),
    ("storage_page", "in_store.png", (1093, 187, 127, 93)),
    ("enhancement_page", "exlevel.png", (87, 280, 220, 233)),
    ("sell_menu", "ljbhfm.png", (853, 300, 300, 237)),
    ("storage_menu", "ljbg.png", (910, 433, 157, 240)),
    ("equipment_enhancement_menu", "lzqh.png", (840, 400, 227, 100)),
    ("servant_enhancement_menu", "czqh.png", (920, 120, 173, 100)),
    ("menu_expanded", "shop.png", (720, 547, 173, 173)),
    ("menu_available", "menu.png", (1033, 533, 247, 187)),
    ("inventory_full", "boxfull.png", (300, 447, 100, 60)),
    ("summon_picker", "close.png", (0, 0, 200, 93)),
    ("back", "back.png", (0, 0, 200, 93)),
    ("enhancement_back", "qh_back.png", (0, 0, 200, 93)),
    ("dialog_close", "x.png", (1213, 7, 60, 53)),
)


class ExpBallRecognizer:
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
        threshold: float = 0.84,
    ) -> dict[str, Any]:
        normalized_server = server.strip().upper()
        if normalized_server not in {"CH", "CNTW", "JP"}:
            raise ValueError("server must be CH, CNTW, or JP.")
        if not 0 <= threshold <= 1:
            raise ValueError("threshold must be between 0 and 1.")

        root = f"expball/{normalized_server}"
        page = self._resources.template_index(prefix=root, limit=200)
        available_paths = {str(entry["path"]) for entry in page["entries"]}
        specs = [
            (name, flow, status, reason, action, f"{root}/{name}.png")
            for name, flow, status, reason, action in _STATE_SPECS
            if f"{root}/{name}.png" in available_paths
        ]
        candidates = [
            {
                "template_path": template_path,
                "threshold": threshold,
                "scales": _SCALES,
            }
            for _name, _flow, _status, _reason, _action, template_path in specs
        ]
        results = (
            self._recognition.match_templates(screenshot, candidates)
            if candidates
            else []
        )
        matches = [
            {
                "name": name,
                "flow": flow,
                "status": status,
                "reason": reason,
                "recommended_action": action,
                **match.to_dict(),
            }
            for match, (name, flow, status, reason, action, _template_path) in zip(
                results,
                specs,
                strict=True,
            )
            if match.matched
        ]
        primary = matches[0] if matches else None
        return {
            "server": normalized_server,
            "state": primary["name"] if primary else "unknown",
            "flow": primary["flow"] if primary else "unknown",
            "status": primary["status"] if primary else "unknown",
            "reason": primary["reason"] if primary else None,
            "recommended_action": (
                primary["recommended_action"] if primary else None
            ),
            "available_template_count": len(candidates),
            "matches": matches,
        }

    def recognize_navigation(
        self,
        screenshot: bytes,
        server: str,
        *,
        threshold: float = 0.84,
    ) -> dict[str, Any]:
        normalized_server = server.strip().upper()
        if normalized_server not in {"CH", "CNTW", "JP"}:
            raise ValueError("server must be CH, CNTW, or JP.")
        if not 0 <= threshold <= 1:
            raise ValueError("threshold must be between 0 and 1.")

        root = f"expball/{normalized_server}"
        page = self._resources.template_index(prefix=root, limit=200)
        available_paths = {str(entry["path"]) for entry in page["entries"]}
        specs = [
            (name, roi, f"{root}/{filename}")
            for name, filename, roi in _NAVIGATION_STATE_SPECS
            if f"{root}/{filename}" in available_paths
        ]
        candidates = [
            {
                "template_path": template_path,
                "threshold": threshold,
                "roi": roi,
                "scales": _SCALES,
            }
            for _name, roi, template_path in specs
        ]
        results = (
            self._recognition.match_templates(screenshot, candidates)
            if candidates
            else []
        )
        matches = [
            {"name": name, **match.to_dict()}
            for match, (name, _roi, _path) in zip(results, specs, strict=True)
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

    def recognize_storage_grid(
        self,
        screenshot: bytes,
        *,
        threshold: float = 0.75,
    ) -> dict[str, Any]:
        if not 0 <= threshold <= 1:
            raise ValueError("threshold must be between 0 and 1.")

        root = "expball/FPgold"
        page = self._resources.template_index(prefix=root, limit=20)
        available_paths = {str(entry["path"]) for entry in page["entries"]}
        template_paths = {
            star: f"{root}/{star}jyz.png"
            for star in _STORAGE_STARS
            if f"{root}/{star}jyz.png" in available_paths
        }
        specs = [
            (slot, star, roi, template_paths[star])
            for slot, roi in enumerate(_STORAGE_CARD_ROIS)
            for star in _STORAGE_STARS
            if star in template_paths
        ]
        candidates = [
            {
                "template_path": template_path,
                "threshold": threshold,
                "roi": roi,
                "scales": _SCALES,
            }
            for _slot, _star, roi, template_path in specs
        ]
        results = (
            self._recognition.match_templates(screenshot, candidates)
            if candidates
            else []
        )
        best_by_slot: dict[int, tuple[int, Any]] = {}
        for result, (slot, star, _roi, _template_path) in zip(
            results,
            specs,
            strict=True,
        ):
            if not result.matched:
                continue
            current = best_by_slot.get(slot)
            if current is None or result.confidence > current[1].confidence:
                best_by_slot[slot] = (star, result)

        slots = []
        for slot, roi in enumerate(_STORAGE_CARD_ROIS):
            x, y, width, height = roi
            best = best_by_slot.get(slot)
            slots.append(
                {
                    "slot": slot,
                    "row": slot // 7,
                    "column": slot % 7,
                    "roi": list(roi),
                    "center": [x + width // 2, y + height // 2],
                    "star": best[0] if best is not None else None,
                    "confidence": (
                        best[1].confidence if best is not None else None
                    ),
                    "match": best[1].to_dict() if best is not None else None,
                }
            )
        return {
            "rows": 3,
            "columns": 7,
            "available_template_count": len(template_paths),
            "candidate_count": len(candidates),
            "recognized_count": len(best_by_slot),
            "slots": slots,
        }

    def recognize_servant_sale_grid(
        self,
        screenshot: bytes,
        *,
        fp_gold_threshold: float = 0.85,
    ) -> dict[str, Any]:
        if not 0 <= fp_gold_threshold <= 1:
            raise ValueError("fp_gold_threshold must be between 0 and 1.")

        root = "expball/FPgold"
        page = self._resources.template_index(prefix=root, limit=20)
        available_paths = {str(entry["path"]) for entry in page["entries"]}
        fp_gold_templates = [
            (name, f"{root}/{name}.png")
            for name in _FP_GOLD_SERVANTS
            if f"{root}/{name}.png" in available_paths
        ]
        specs = [
            (slot, name, roi, template_path)
            for slot, roi in enumerate(_STORAGE_CARD_ROIS)
            for name, template_path in fp_gold_templates
        ]
        candidates = [
            {
                "template_path": template_path,
                "threshold": fp_gold_threshold,
                "roi": roi,
                "scales": _SCALES,
            }
            for _slot, _name, roi, template_path in specs
        ]
        results = (
            self._recognition.match_templates(screenshot, candidates)
            if candidates
            else []
        )
        best_fp_gold_by_slot: dict[int, tuple[str, Any]] = {}
        for result, (slot, name, _roi, _template_path) in zip(
            results,
            specs,
            strict=True,
        ):
            if not result.matched:
                continue
            current = best_fp_gold_by_slot.get(slot)
            if current is None or result.confidence > current[1].confidence:
                best_fp_gold_by_slot[slot] = (name, result)

        frame_by_slot = _inspect_servant_frame_colors(screenshot)
        slots: list[dict[str, Any]] = []
        fp_gold_slots: list[int] = []
        need_lock_slots: list[int] = []
        sellable_slots: list[int] = []
        for slot, roi in enumerate(_STORAGE_CARD_ROIS):
            x, y, width, height = roi
            frame_info = frame_by_slot.get(slot, {})
            frame_type = frame_info.get("frame_type")
            rarity_group = frame_info.get("rarity_group")
            locked = bool(frame_info.get("locked", False))
            fp_best = best_fp_gold_by_slot.get(slot)
            fp_gold = fp_best[0] if fp_best is not None else None
            if fp_gold is not None:
                fp_gold_slots.append(slot)
            need_lock = bool(
                frame_type == "gold_unlocked" and fp_gold is None
            )
            if need_lock:
                need_lock_slots.append(slot)
            sellable_servant = bool(
                frame_type in {"bronze", "silver"}
                or (frame_type == "gold_unlocked" and fp_gold is not None)
                or (frame_type is None and fp_gold is not None)
            )
            if sellable_servant:
                sellable_slots.append(slot)
            slots.append(
                {
                    "slot": slot,
                    "row": slot // 7,
                    "column": slot % 7,
                    "roi": list(roi),
                    "center": [x + width // 2, y + height // 2],
                    "frame_type": frame_type,
                    "rarity_group": rarity_group,
                    "locked": locked,
                    "rgb": frame_info.get("rgb"),
                    "fp_gold": fp_gold,
                    "fp_gold_confidence": (
                        fp_best[1].confidence if fp_best is not None else None
                    ),
                    "fp_gold_match": (
                        fp_best[1].to_dict() if fp_best is not None else None
                    ),
                    "need_lock": need_lock,
                    "sellable_servant": sellable_servant,
                }
            )
        return {
            "rows": 3,
            "columns": 7,
            "available_fp_gold_template_count": len(fp_gold_templates),
            "candidate_count": len(candidates),
            "fp_gold_count": len(fp_gold_slots),
            "fp_gold_slots": fp_gold_slots,
            "need_lock_count": len(need_lock_slots),
            "need_lock_slots": need_lock_slots,
            "sellable_count": len(sellable_slots),
            "sellable_slots": sellable_slots,
            "slots": slots,
        }

    def recognize_servant_level(
        self,
        screenshot: bytes,
        *,
        threshold: float = 0.6,
    ) -> dict[str, Any]:
        if not 0 <= threshold <= 1:
            raise ValueError("threshold must be between 0 and 1.")

        root = "expball/digits"
        page = self._resources.template_index(prefix=root, limit=20)
        available_paths = {str(entry["path"]) for entry in page["entries"]}
        template_paths = {
            digit: f"{root}/{digit}.png"
            for digit in _SERVANT_LEVEL_DIGITS
            if f"{root}/{digit}.png" in available_paths
        }
        slot_defs = [
            *tuple(
                ("left", index, roi)
                for index, roi in enumerate(_SERVANT_LEVEL_LEFT_ROIS)
            ),
            *tuple(
                ("right", index, roi)
                for index, roi in enumerate(_SERVANT_LEVEL_RIGHT_ROIS)
            ),
        ]
        specs = [
            (slot_index, side, index, digit, roi, template_paths[digit])
            for slot_index, (side, index, roi) in enumerate(slot_defs)
            for digit in _SERVANT_LEVEL_DIGITS
            if digit in template_paths
        ]
        candidates = [
            {
                "template_path": template_path,
                "threshold": threshold,
                "roi": roi,
                "scales": _SERVANT_LEVEL_DIGIT_SCALES,
                "use_alpha_mask": False,
            }
            for _slot_index, _side, _index, _digit, roi, template_path in specs
        ]
        results = (
            self._recognition.match_templates(screenshot, candidates)
            if candidates
            else []
        )
        best_by_slot: dict[int, tuple[int, Any]] = {}
        for result, (slot_index, _side, _index, digit, _roi, _path) in zip(
            results,
            specs,
            strict=True,
        ):
            if not result.matched:
                continue
            current = best_by_slot.get(slot_index)
            if current is None or result.confidence > current[1].confidence:
                best_by_slot[slot_index] = (digit, result)

        left_digits: list[int] = []
        right_digits: list[int] = []
        slots: list[dict[str, Any]] = []
        for slot_index, (side, index, roi) in enumerate(slot_defs):
            best = best_by_slot.get(slot_index)
            digit = best[0] if best is not None else None
            if digit is not None:
                if side == "left":
                    left_digits.append(digit)
                else:
                    right_digits.append(digit)
            slots.append(
                {
                    "slot": slot_index,
                    "side": side,
                    "index": index,
                    "roi": list(roi),
                    "digit": digit,
                    "confidence": (
                        best[1].confidence if best is not None else None
                    ),
                    "match": best[1].to_dict() if best is not None else None,
                }
            )

        current_level = 0
        for digit in left_digits:
            current_level = current_level * 10 + digit
        max_level = 0
        for digit in right_digits:
            max_level = max_level * 10 + digit
        if left_digits and right_digits and current_level + 100 <= max_level:
            current_level += 100
        valid = bool(
            left_digits
            and right_digits
            and current_level > 0
            and max_level >= 20
            and current_level <= max_level
        )
        return {
            "valid": valid,
            "current_level": current_level if valid else None,
            "max_level": max_level if valid else None,
            "is_max_level": bool(valid and current_level >= max_level),
            "raw_current_level": current_level,
            "raw_max_level": max_level,
            "left_digits": left_digits,
            "right_digits": right_digits,
            "available_template_count": len(template_paths),
            "candidate_count": len(candidates),
            "slots": slots,
        }

    def recognize_command_code_sale_grid(
        self,
        screenshot: bytes,
        server: str,
        *,
        inscribed_threshold: float = 0.7,
        empty_threshold: float = 0.8,
        locker_threshold: float = 0.7,
    ) -> dict[str, Any]:
        normalized_server = server.strip().upper()
        if normalized_server not in {"CH", "CNTW", "JP"}:
            raise ValueError("server must be CH, CNTW, or JP.")
        if not 0 <= inscribed_threshold <= 1:
            raise ValueError("inscribed_threshold must be between 0 and 1.")
        if not 0 <= empty_threshold <= 1:
            raise ValueError("empty_threshold must be between 0 and 1.")
        if not 0 <= locker_threshold <= 1:
            raise ValueError("locker_threshold must be between 0 and 1.")

        root = f"expball/{normalized_server}"
        page = self._resources.template_index(prefix=root, limit=200)
        available_paths = {str(entry["path"]) for entry in page["entries"]}

        specs: list[tuple[str, int | None, str, dict[str, Any]]] = []
        for empty_name in ("no_wenzhang.png", "no_wenzhang_1.png"):
            path = f"{root}/{empty_name}"
            if path in available_paths:
                specs.append(
                    (
                        "empty",
                        None,
                        empty_name[:-4],
                        {
                            "template_path": path,
                            "threshold": empty_threshold,
                            "roi": _NO_COMMAND_CODE_ROI,
                            "scales": _SCALES,
                        },
                    )
                )
        locker_path = f"{root}/locker.png"
        if locker_path in available_paths:
            specs.append(
                (
                    "locker",
                    0,
                    "locker",
                    {
                        "template_path": locker_path,
                        "threshold": locker_threshold,
                        "roi": _FIRST_CARD_LOCKER_ROI,
                        "scales": _SCALES,
                    },
                )
            )
        kyz_path = f"{root}/kyz.png"
        if kyz_path in available_paths:
            for slot, roi in enumerate(_COMMAND_CODE_CARD_ROIS):
                specs.append(
                    (
                        "inscribed",
                        slot,
                        "kyz",
                        {
                            "template_path": kyz_path,
                            "threshold": inscribed_threshold,
                            "roi": roi,
                            "scales": _SCALES,
                        },
                    )
                )

        candidates = [candidate for _kind, _slot, _name, candidate in specs]
        results = (
            self._recognition.match_templates(screenshot, candidates)
            if candidates
            else []
        )

        empty_matched = False
        first_slot_locked = False
        inscribed_by_slot: dict[int, Any] = {}
        for result, (kind, slot, _name, _candidate) in zip(
            results,
            specs,
            strict=True,
        ):
            if not result.matched:
                continue
            if kind == "empty":
                empty_matched = True
            elif kind == "locker":
                first_slot_locked = True
            elif kind == "inscribed" and slot is not None:
                inscribed_by_slot[slot] = result

        slots: list[dict[str, Any]] = []
        inscribed_slots: list[int] = []
        for slot, roi in enumerate(_COMMAND_CODE_CARD_ROIS):
            row = slot // 7
            column = slot % 7
            rx, ry, rw, rh = roi
            inscribed_match = inscribed_by_slot.get(slot)
            inscribed = inscribed_match is not None
            if inscribed:
                inscribed_slots.append(slot)
            slots.append(
                {
                    "slot": slot,
                    "row": row,
                    "column": column,
                    "roi": list(roi),
                    "center": [rx + rw // 2, ry + rh // 2],
                    "inscribed": inscribed,
                    "confidence": (
                        inscribed_match.confidence if inscribed_match else None
                    ),
                    "match": (
                        inscribed_match.to_dict() if inscribed_match else None
                    ),
                }
            )
        return {
            "server": normalized_server,
            "rows": 3,
            "columns": 7,
            "inscribed_threshold": inscribed_threshold,
            "empty_threshold": empty_threshold,
            "locker_threshold": locker_threshold,
            "empty": empty_matched,
            "first_slot_locked": first_slot_locked,
            "inscribed_slots": inscribed_slots,
            "inscribed_count": len(inscribed_slots),
            "slots": slots,
        }

    def recognize_ce_bomb_grid(
        self,
        screenshot: bytes,
        server: str,
        *,
        locker_threshold: float = 0.7,
        mark_threshold: float = 0.6,
    ) -> dict[str, Any]:
        normalized_server = server.strip().upper()
        if normalized_server not in {"CH", "CNTW", "JP"}:
            raise ValueError("server must be CH, CNTW, or JP.")
        if not 0 <= locker_threshold <= 1:
            raise ValueError("locker_threshold must be between 0 and 1.")
        if not 0 <= mark_threshold <= 1:
            raise ValueError("mark_threshold must be between 0 and 1.")

        frame_colors = _inspect_ce_bomb_frame_colors(screenshot)
        root = f"expball/{normalized_server}"
        page = self._resources.template_index(prefix=root, limit=200)
        available_paths = {str(entry["path"]) for entry in page["entries"]}

        specs: list[tuple[str, int, dict[str, Any]]] = []
        locker_path = f"{root}/locker.png"
        if locker_path in available_paths:
            for slot, roi in enumerate(_CE_BOMB_LOCK_ROIS):
                specs.append(
                    (
                        "locker",
                        slot,
                        {
                            "template_path": locker_path,
                            "threshold": locker_threshold,
                            "roi": roi,
                            "scales": _SCALES,
                        },
                    )
                )
        mark_path = f"{root}/biaoji.png"
        if mark_path in available_paths:
            for slot, roi in enumerate(_CE_BOMB_MARK_ROIS):
                specs.append(
                    (
                        "mark",
                        slot,
                        {
                            "template_path": mark_path,
                            "threshold": mark_threshold,
                            "roi": roi,
                            "scales": _SCALES,
                        },
                    )
                )

        candidates = [candidate for _kind, _slot, candidate in specs]
        results = (
            self._recognition.match_templates(screenshot, candidates)
            if candidates
            else []
        )

        locked_by_slot: dict[int, Any] = {}
        marked_by_slot: dict[int, Any] = {}
        for result, (kind, slot, _candidate) in zip(
            results,
            specs,
            strict=True,
        ):
            if not result.matched:
                continue
            if kind == "locker":
                locked_by_slot[slot] = result
            elif kind == "mark":
                marked_by_slot[slot] = result

        slots: list[dict[str, Any]] = []
        full_level_slots: list[int] = []
        need_lock_slots: list[int] = []
        need_mark_slots: list[int] = []
        need_store_slots: list[int] = []

        for slot, roi in enumerate(_CE_BOMB_CARD_ROIS):
            row = slot // 7
            column = slot % 7
            color_info = frame_colors.get(slot)
            full_level = bool(color_info and color_info.get("full_level"))
            locked = slot in locked_by_slot
            marked = slot in marked_by_slot
            need_lock = bool(full_level and not locked)
            need_mark = bool(full_level and not marked)
            need_store = bool(locked and marked)
            if full_level:
                full_level_slots.append(slot)
            if need_lock:
                need_lock_slots.append(slot)
            if need_mark:
                need_mark_slots.append(slot)
            if need_store:
                need_store_slots.append(slot)
            center = [
                round((90 + column * 200 + 113) * 2 / 3),
                round((275 + row * 213 + 105.5) * 2 / 3),
            ]
            slots.append(
                {
                    "slot": slot,
                    "row": row,
                    "column": column,
                    "roi": list(roi),
                    "center": center,
                    "full_level": full_level,
                    "locked": locked,
                    "marked": marked,
                    "need_lock": need_lock,
                    "need_mark": need_mark,
                    "need_store": need_store,
                    "frame_rgb": color_info.get("rgb") if color_info else None,
                    "full_distance": (
                        color_info.get("full_distance") if color_info else None
                    ),
                }
            )
        return {
            "server": normalized_server,
            "rows": 3,
            "columns": 7,
            "locker_threshold": locker_threshold,
            "mark_threshold": mark_threshold,
            "full_level_slots": full_level_slots,
            "full_level_count": len(full_level_slots),
            "all_full_level": bool(slots and len(full_level_slots) == len(slots)),
            "last_slot_full_level": bool(slots and slots[-1]["full_level"]),
            "need_lock_slots": need_lock_slots,
            "need_lock_count": len(need_lock_slots),
            "need_mark_slots": need_mark_slots,
            "need_mark_count": len(need_mark_slots),
            "need_store_slots": need_store_slots,
            "need_store_count": len(need_store_slots),
            "slots": slots,
        }

    def recognize_summon_lock_targets(
        self,
        screenshot: bytes,
        *,
        targets: Sequence[str | dict[str, Any]] | None = None,
        threshold: float = 0.8,
    ) -> dict[str, Any]:
        if not 0 <= threshold <= 1:
            raise ValueError("threshold must be between 0 and 1.")

        need_lock_page = self._resources.template_index(
            prefix="expball/needLock",
            limit=200,
        )
        need_lock_paths = [
            str(entry["path"]) for entry in need_lock_page["entries"]
        ]
        need_lock_by_name: dict[str, str] = {}
        available_targets: list[str] = []
        for path in need_lock_paths:
            posix = PurePosixPath(path)
            available_targets.append(posix.name)
            need_lock_by_name[path.lower()] = path
            need_lock_by_name[posix.name.lower()] = path
            need_lock_by_name[posix.stem.lower()] = path

        fp_gold_page = self._resources.template_index(
            prefix="expball/FPgold",
            limit=50,
        )
        fp_gold_paths = {
            str(entry["path"]) for entry in fp_gold_page["entries"]
        }
        fp_gold_by_name: dict[str, list[str]] = {}
        for name in _FP_GOLD_SERVANTS:
            candidate_path = f"expball/FPgold/{name}.png"
            if candidate_path in fp_gold_paths:
                fp_gold_by_name[name] = [candidate_path]
                fp_gold_by_name[f"{name}.png"] = [candidate_path]
                fp_gold_by_name[candidate_path.lower()] = [candidate_path]
        hakuno_paths = [
            f"expball/FPgold/{name}.png"
            for name in ("hakuno_0", "hakuno_1")
            if f"expball/FPgold/{name}.png" in fp_gold_paths
        ]
        if hakuno_paths:
            fp_gold_by_name["hakuno"] = hakuno_paths

        requested_names: list[str] = []
        if targets is None:
            requested_names = list(available_targets)
        else:
            for item in targets:
                if isinstance(item, str):
                    cleaned = item.strip()
                elif isinstance(item, dict):
                    raw_target = (
                        item.get("target")
                        if item.get("target") is not None
                        else item.get("path")
                    )
                    cleaned = (
                        str(raw_target).strip()
                        if raw_target is not None
                        else ""
                    )
                else:
                    raise ValueError(
                        "Each lock target must be a string or object."
                    )
                if not cleaned:
                    raise ValueError(
                        "Each lock target must specify a non-empty name."
                    )
                if cleaned not in requested_names:
                    requested_names.append(cleaned)

        resolved_specs: list[tuple[str, str]] = []
        for target_name in requested_names:
            key = target_name.lower()
            if key in need_lock_by_name:
                resolved_specs.append((target_name, need_lock_by_name[key]))
            elif key in fp_gold_by_name:
                for path in fp_gold_by_name[key]:
                    resolved_specs.append((target_name, path))
            else:
                try:
                    self._resources.resolve_template(target_name)
                except Exception as exc:
                    raise ValueError(
                        f"Unknown summon lock target: {target_name}"
                    ) from exc
                resolved_specs.append((target_name, target_name))

        raw_matches: list[dict[str, Any]] = []
        for target_name, template_path in resolved_specs:
            scales = self._summon_lock_template_scales(template_path)
            matched_list = self._recognition.match_template_all(
                screenshot,
                template_path,
                threshold=threshold,
                scales=scales,
            )
            for match in matched_list:
                raw_matches.append(
                    {
                        "target": target_name,
                        "template_path": template_path,
                        **match.to_dict(),
                    }
                )

        selected_matches: list[dict[str, Any]] = []
        for candidate in sorted(
            raw_matches,
            key=lambda item: float(item.get("confidence", 0.0)),
            reverse=True,
        ):
            if any(
                _boxes_overlap(candidate, existing) >= 0.3
                for existing in selected_matches
            ):
                continue
            selected_matches.append(candidate)

        selected_matches.sort(
            key=lambda item: (
                int(item["top_left"][1]),
                int(item["top_left"][0]),
            )
        )
        return {
            "threshold": threshold,
            "available_targets": available_targets,
            "requested_targets": requested_names,
            "target_count": len(requested_names),
            "match_count": len(selected_matches),
            "matches": selected_matches,
        }

    def _summon_lock_template_scales(
        self,
        template_path: str,
    ) -> tuple[float, ...]:
        extra_scales: list[float] = []
        try:
            resolved = self._resources.resolve_template(template_path)
            with Image.open(resolved) as img:
                width, height = img.size
            if width > 0 and height > 0:
                s = (width / 164 + height / 176) / 2
                res_w = int(1280 * s)
                res_h = int(720 * s)
                if res_w > 0 and res_h > 0:
                    scale_720 = min(1280 / res_w, 720 / res_h)
                    extra_scales.extend(
                        [round(scale_720, 4), round(scale_720 * 1.5, 4)]
                    )
        except Exception:
            pass
        return tuple(dict.fromkeys((*_SCALES, *extra_scales)))

    def recognize_servant_target(
        self,
        screenshot: bytes,
        server: str,
        *,
        target: str | None = None,
        threshold: float = 0.85,
        scroll_end_threshold: float = 0.8,
    ) -> dict[str, Any]:
        normalized_server = server.strip().upper()
        if normalized_server not in {"CH", "CNTW", "JP"}:
            raise ValueError("server must be CH, CNTW, or JP.")
        if not 0 <= threshold <= 1:
            raise ValueError("threshold must be between 0 and 1.")
        if not 0 <= scroll_end_threshold <= 1:
            raise ValueError("scroll_end_threshold must be between 0 and 1.")

        custom_page = self._resources.template_index(
            prefix="expball/levelupServant",
            limit=200,
        )
        custom_by_name: dict[str, str] = {}
        available_custom_targets: list[str] = []
        for entry in custom_page.get("entries", []):
            path = str(entry["path"])
            stem = PurePosixPath(path).stem
            name = PurePosixPath(path).name
            custom_by_name[stem.lower()] = path
            custom_by_name[name.lower()] = path
            available_custom_targets.append(stem)

        servant_face_page = self._resources.template_index(
            prefix="servantface",
            limit=200,
        )
        servant_face_by_name: dict[str, str] = {}
        for entry in servant_face_page.get("entries", []):
            path = str(entry["path"])
            stem = PurePosixPath(path).stem
            name = PurePosixPath(path).name
            servant_face_by_name[stem.lower()] = path
            servant_face_by_name[name.lower()] = path

        server_page = self._resources.template_index(
            prefix=f"expball/{normalized_server}",
            limit=200,
        )
        server_paths = {
            str(entry["path"]) for entry in server_page.get("entries", [])
        }
        scroll_end_path = f"expball/{normalized_server}/scrollEnd.png"
        has_scroll_end = scroll_end_path in server_paths

        normalized_target = target.strip() if isinstance(target, str) else ""
        template_path: str | None = None
        is_custom = False
        if normalized_target:
            key = normalized_target.lower()
            if key in custom_by_name:
                template_path = custom_by_name[key]
                is_custom = True
            elif key in servant_face_by_name:
                template_path = servant_face_by_name[key]
                is_custom = False
            else:
                direct_candidates = [normalized_target]
                if not normalized_target.lower().endswith((".png", ".jpg")):
                    direct_candidates.extend(
                        [
                            f"servantface/{normalized_target}.png",
                            f"expball/levelupServant/{normalized_target}.png",
                            f"expball/levelupServant/{normalized_target}.jpg",
                        ]
                    )
                else:
                    direct_candidates.extend(
                        [
                            f"servantface/{normalized_target}",
                            f"expball/levelupServant/{normalized_target}",
                        ]
                    )
                for candidate_path in direct_candidates:
                    try:
                        self._resources.resolve_template(candidate_path)
                        template_path = candidate_path
                        is_custom = candidate_path.startswith(
                            "expball/levelupServant/"
                        )
                        break
                    except Exception:
                        continue
                if template_path is None:
                    raise ValueError(
                        f"Unknown servant enhancement target: {normalized_target}"
                    )

        candidates: list[dict[str, Any]] = []
        if template_path is not None:
            crop, scales = self._servant_target_crop_and_scales(
                template_path,
                custom=is_custom,
            )
            target_candidate: dict[str, Any] = {
                "template_path": template_path,
                "threshold": threshold,
                "roi": _SERVANT_TARGET_ROI,
                "scales": scales,
            }
            if crop is not None:
                target_candidate["crop"] = crop
            candidates.append(target_candidate)
        if has_scroll_end:
            candidates.append(
                {
                    "template_path": scroll_end_path,
                    "threshold": scroll_end_threshold,
                    "roi": _SERVANT_SCROLL_END_ROI,
                    "scales": _SCALES,
                }
            )

        results = (
            self._recognition.match_templates(screenshot, candidates)
            if candidates
            else []
        )
        result_index = 0
        target_match = None
        if template_path is not None and result_index < len(results):
            target_match = results[result_index]
            result_index += 1
        scroll_end_match = None
        if has_scroll_end and result_index < len(results):
            scroll_end_match = results[result_index]

        matched = bool(target_match is not None and target_match.matched)
        scroll_end = bool(
            scroll_end_match is not None and scroll_end_match.matched
        )
        return {
            "server": normalized_server,
            "target": normalized_target or None,
            "template_path": template_path,
            "custom": is_custom,
            "threshold": threshold,
            "scroll_end_threshold": scroll_end_threshold,
            "roi": list(_SERVANT_TARGET_ROI),
            "available_custom_targets": available_custom_targets,
            "matched": matched,
            "confidence": (
                round(float(target_match.confidence), 4)
                if target_match is not None
                else 0.0
            ),
            "center": (
                list(target_match.center)
                if matched
                and target_match is not None
                and target_match.center is not None
                else None
            ),
            "match": (
                target_match.to_dict()
                if matched and target_match is not None
                else None
            ),
            "scroll_end": scroll_end,
            "scroll_end_match": (
                scroll_end_match.to_dict()
                if scroll_end and scroll_end_match is not None
                else None
            ),
        }

    def _servant_target_crop_and_scales(
        self,
        template_path: str,
        *,
        custom: bool,
    ) -> tuple[tuple[int, int, int, int] | None, tuple[float, ...]]:
        crop: tuple[int, int, int, int] | None = None
        extra_scales: list[float] = []
        try:
            resolved = self._resources.resolve_template(template_path)
            with Image.open(resolved) as img:
                width, height = img.size
            if width > 0 and height > 0:
                if custom:
                    scale = (width / 175 + height / 191) / 2
                    left = max(0, min(width - 1, round(16 * scale)))
                    top = max(0, min(height - 1, round(34 * scale)))
                    right = max(left + 1, min(width, round(175 * scale)))
                    bottom = max(top + 1, min(height, round(118 * scale)))
                    crop = (left, top, right - left, bottom - top)
                    res_w = int(1920 * scale)
                    res_h = int(1080 * scale)
                    if res_w > 0 and res_h > 0:
                        scale_720 = min(1280 / res_w, 720 / res_h)
                        scale_1080 = min(1920 / res_w, 1080 / res_h)
                        extra_scales.extend(
                            [round(scale_720, 4), round(scale_1080, 4)]
                        )
                else:
                    left = max(0, min(width - 1, round(35 * width / 170)))
                    top = max(0, min(height - 1, round(30 * height / 170)))
                    right = max(left + 1, min(width, round(160 * width / 170)))
                    bottom = max(top + 1, min(height, round(110 * height / 170)))
                    crop = (left, top, right - left, bottom - top)
                    scale_1080 = 170 / width
                    scale_720 = scale_1080 * (2 / 3)
                    extra_scales.extend(
                        [round(scale_720, 4), round(scale_1080, 4)]
                    )
        except Exception:
            pass
        return crop, tuple(dict.fromkeys((*extra_scales, *_SCALES)))


def _inspect_servant_frame_colors(
    screenshot: bytes,
) -> dict[int, dict[str, Any]]:
    try:
        with Image.open(BytesIO(screenshot)) as source:
            image = source.convert("RGB")
    except (UnidentifiedImageError, OSError, ValueError):
        return {}

    width, height = image.size
    if width <= 0 or height <= 0:
        return {}
    scale = min(width / 1920, height / 1080)
    dx = (width - 1920 * scale) / 2
    dy = (height - 1080 * scale) / 2
    result: dict[int, dict[str, Any]] = {}

    for slot in range(21):
        row = slot // 7
        column = slot % 7
        left_1080 = 112 + column * 200
        top_1080 = 271 + row * 213
        crop_left = max(0, min(width, round((left_1080 + 10) * scale + dx)))
        crop_top = max(0, min(height, round((top_1080 + 180) * scale + dy)))
        crop_right = max(
            crop_left,
            min(width, round((left_1080 + 50) * scale + dx)),
        )
        crop_bottom = max(
            crop_top,
            min(height, round((top_1080 + 190) * scale + dy)),
        )
        if crop_right <= crop_left or crop_bottom <= crop_top:
            continue
        patch = image.crop((crop_left, crop_top, crop_right, crop_bottom))
        raw_bytes = patch.tobytes()
        if not raw_bytes:
            continue
        count = len(raw_bytes) // 3
        if count <= 0:
            continue
        mean_r = sum(raw_bytes[0::3]) / count
        mean_g = sum(raw_bytes[1::3]) / count
        mean_b = sum(raw_bytes[2::3]) / count
        distances = [
            (
                (mean_r - target_rgb[0]) ** 2
                + (mean_g - target_rgb[1]) ** 2
                + (mean_b - target_rgb[2]) ** 2,
                frame_type,
                rarity_group,
                locked,
            )
            for frame_type, rarity_group, locked, target_rgb in _SERVANT_FRAME_SPECS
        ]
        min_distance, best_frame, best_rarity, best_locked = min(
            distances,
            key=lambda item: item[0],
        )
        if min_distance > 8000:
            result[slot] = {
                "frame_type": None,
                "rarity_group": None,
                "locked": False,
                "rgb": [round(mean_r, 1), round(mean_g, 1), round(mean_b, 1)],
            }
        else:
            result[slot] = {
                "frame_type": best_frame,
                "rarity_group": best_rarity,
                "locked": best_locked,
                "rgb": [round(mean_r, 1), round(mean_g, 1), round(mean_b, 1)],
            }
    return result


def _inspect_ce_bomb_frame_colors(
    screenshot: bytes,
) -> dict[int, dict[str, Any]]:
    try:
        with Image.open(BytesIO(screenshot)) as source:
            image = source.convert("RGB")
    except (UnidentifiedImageError, OSError, ValueError):
        return {}

    width, height = image.size
    if width <= 0 or height <= 0:
        return {}
    scale = min(width / 1920, height / 1080)
    dx = (width - 1920 * scale) / 2
    dy = (height - 1080 * scale) / 2
    result: dict[int, dict[str, Any]] = {}

    for slot in range(21):
        row = slot // 7
        column = slot % 7
        left_1080 = 90 + column * 200
        top_1080 = 275 + row * 213
        crop_left = max(0, min(width, round((left_1080 + 30) * scale + dx)))
        crop_top = max(0, min(height, round((top_1080 + 185) * scale + dy)))
        crop_right = max(
            crop_left,
            min(width, round((left_1080 + 70) * scale + dy if False else (left_1080 + 70) * scale + dx)),
        )
        crop_bottom = max(
            crop_top,
            min(height, round((top_1080 + 195) * scale + dy)),
        )
        if crop_right <= crop_left or crop_bottom <= crop_top:
            continue
        patch = image.crop((crop_left, crop_top, crop_right, crop_bottom))
        raw_bytes = patch.tobytes()
        if not raw_bytes:
            continue
        count = len(raw_bytes) // 3
        if count <= 0:
            continue
        mean_r = sum(raw_bytes[0::3]) / count
        mean_g = sum(raw_bytes[1::3]) / count
        mean_b = sum(raw_bytes[2::3]) / count
        dist_full = (
            (mean_r - _CE_FULL_LV_RGB[0]) ** 2
            + (mean_g - _CE_FULL_LV_RGB[1]) ** 2
            + (mean_b - _CE_FULL_LV_RGB[2]) ** 2
        )
        dist_non_full = (
            (mean_r - _CE_NON_FULL_LV_RGB[0]) ** 2
            + (mean_g - _CE_NON_FULL_LV_RGB[1]) ** 2
            + (mean_b - _CE_NON_FULL_LV_RGB[2]) ** 2
        )
        result[slot] = {
            "full_level": bool(dist_full <= dist_non_full and dist_full < 500),
            "full_distance": round(dist_full, 2),
            "non_full_distance": round(dist_non_full, 2),
            "rgb": [round(mean_r, 1), round(mean_g, 1), round(mean_b, 1)],
        }
    return result


def _boxes_overlap(first: dict[str, Any], second: dict[str, Any]) -> float:
    first_x, first_y = int(first["top_left"][0]), int(first["top_left"][1])
    second_x, second_y = int(second["top_left"][0]), int(second["top_left"][1])
    first_w, first_h = int(first["size"][0]), int(first["size"][1])
    second_w, second_h = int(second["size"][0]), int(second["size"][1])
    overlap_w = max(
        0,
        min(first_x + first_w, second_x + second_w) - max(first_x, second_x),
    )
    overlap_h = max(
        0,
        min(first_y + first_h, second_y + second_h) - max(first_y, second_y),
    )
    overlap_area = overlap_w * overlap_h
    if overlap_area <= 0:
        return 0.0
    union_area = first_w * first_h + second_w * second_h - overlap_area
    return overlap_area / union_area if union_area > 0 else 0.0
