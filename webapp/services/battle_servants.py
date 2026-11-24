from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from webapp.core.errors import AppError, ErrorCode
from webapp.services.recognition import RecognitionService

try:
    import cv2
    import numpy as np
except ImportError:  # pragma: no cover - dependency availability is environment-specific
    cv2 = None
    np = None


CLASS_LIST: tuple[str, ...] = (
    "Saber",
    "Archer",
    "Lancer",
    "Rider",
    "Caster",
    "Assassin",
    "Berserker",
    "Alterego",
    "Avenger",
    "Foreigner",
    "MoonCancer",
    "Pretender",
    "Ruler",
    "Shielder",
    "Beast",
)

BATTLE_CLASS_ICON_RECTS_1080: tuple[tuple[int, int, int, int], ...] = (
    (20, 925, 175, 1080),
    (496, 925, 651, 1080),
    (972, 925, 1127, 1080),
)
STATUS_RECTS_1080: tuple[tuple[int, int, int, int], ...] = (
    (189, 600, 289, 710),
    (665, 600, 765, 710),
    (1141, 600, 1241, 710),
)

BATTLE_CLASS_ICON_ROIS: tuple[tuple[int, int, int, int], ...] = (
    (13, 617, 104, 103),
    (331, 617, 103, 103),
    (648, 617, 103, 103),
)
STATUS_ROIS: tuple[tuple[int, int, int, int], ...] = (
    (126, 400, 67, 73),
    (443, 400, 67, 73),
    (761, 400, 66, 73),
)

CLASS_ICON_TARGET_SIZE = (155, 155)
STATUS_TILE_SIZE = (50, 55)
STATUS_ALLOW_OFFSET = 5
STATUS_GRID_COLUMNS = 10
LANCER_FALLBACK_SERVANT = "堂吉诃德"


class FrontlineServantRecognizer:
    def __init__(self, recognition_or_resources: Any) -> None:
        self._resources = getattr(
            recognition_or_resources,
            "_resources",
            recognition_or_resources,
        )
        self._status_info_cache: dict[str, list[str]] | None = None
        self._status_sheet_cache: dict[str, Any] = {}
        self._class_icon_cache: dict[str, Any] = {}
        self._servant_catalog_cache: dict[str, dict[str, tuple[str, dict[str, Any]]]] = {}

    def invalidate_cache(self) -> None:
        self._status_info_cache = None
        self._status_sheet_cache.clear()
        self._servant_catalog_cache.clear()

    def has_assets(self) -> bool:
        assets_dir = getattr(self._resources, "assets_dir", None)
        if not isinstance(assets_dir, Path):
            return False
        status_info = assets_dir / "status" / "status_info.json"
        class_dir = assets_dir / "battle" / "public" / "classIcon"
        return status_info.is_file() and class_dir.is_dir()

    def recognize_classes(
        self,
        screenshot: bytes,
        *,
        present: tuple[bool, bool, bool] | list[bool] = (True, True, True),
        threshold: float = 0.6,
    ) -> list[str | None]:
        self._validate_present(present)
        self._validate_threshold(threshold, "threshold")
        image = self._decode_screenshot(screenshot)
        height, width = image.shape[:2]
        scale_x = width / 1920.0
        scale_y = height / 1080.0

        classes: list[str | None] = [None, None, None]
        for slot_index, occupied in enumerate(present):
            if not occupied:
                continue
            crop = self._crop_scaled_rect(
                image,
                BATTLE_CLASS_ICON_RECTS_1080[slot_index],
                scale_x,
                scale_y,
            )
            if crop.size == 0:
                continue
            resized = cv2.resize(
                crop,
                CLASS_ICON_TARGET_SIZE,
                interpolation=cv2.INTER_LINEAR,
            )
            crop_gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
            best_class: str | None = None
            best_score = -1.0
            for class_name in CLASS_LIST:
                template = self._load_class_icon_gray(class_name)
                if template is None:
                    continue
                if (
                    template.shape[0] > crop_gray.shape[0]
                    or template.shape[1] > crop_gray.shape[1]
                ):
                    continue
                result = cv2.matchTemplate(
                    crop_gray,
                    template,
                    cv2.TM_CCOEFF_NORMED,
                )
                _, max_val, _, _ = cv2.minMaxLoc(result)
                score = float(max_val)
                if score >= threshold and score > best_score:
                    best_score = score
                    best_class = class_name
            classes[slot_index] = best_class
        return classes

    def recognize_names(
        self,
        screenshot: bytes,
        *,
        classes: list[str | None] | tuple[str | None, ...] | None = None,
        present: tuple[bool, bool, bool] | list[bool] = (True, True, True),
        class_threshold: float = 0.6,
        threshold: float = 0.7,
        allow_offset: int = STATUS_ALLOW_OFFSET,
        final_attempt: bool = False,
    ) -> dict[str, Any]:
        self._validate_present(present)
        self._validate_threshold(class_threshold, "class_threshold")
        self._validate_threshold(threshold, "threshold")
        image = self._decode_screenshot(screenshot)
        resolved_classes = (
            list(classes)
            if classes is not None
            else self.recognize_classes(
                screenshot,
                present=present,
                threshold=class_threshold,
            )
        )
        if len(resolved_classes) != 3:
            raise ValueError("classes must contain exactly three entries.")

        tile_w, tile_h = STATUS_TILE_SIZE
        height, width = image.shape[:2]
        scale_x = width / 1920.0
        scale_y = height / 1080.0
        status_info = self._load_status_info()

        raw_names: list[str | int | None] = [
            -1 if class_name is not None else None for class_name in resolved_classes
        ]
        found = any(class_name is not None for class_name in resolved_classes)

        for slot_index, class_name in enumerate(resolved_classes):
            if not class_name:
                continue
            sheet_gray = self._load_status_sheet_gray(class_name)
            class_entries = status_info.get(class_name)
            if sheet_gray is None or not isinstance(class_entries, list):
                found = False
                break
            crop = self._crop_scaled_rect(
                image,
                STATUS_RECTS_1080[slot_index],
                scale_x,
                scale_y,
            )
            if crop.size == 0:
                found = False
                break
            im = cv2.resize(crop, (tile_w, tile_h), interpolation=cv2.INTER_LINEAR)
            im_gray = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)
            if (
                im_gray.shape[0] > sheet_gray.shape[0]
                or im_gray.shape[1] > sheet_gray.shape[1]
            ):
                found = False
                break

            result = cv2.matchTemplate(sheet_gray, im_gray, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(result)
            center = (
                round(max_loc[0] + im_gray.shape[1] / 2),
                round(max_loc[1] + im_gray.shape[0] / 2),
            )

            chosen_point: tuple[int, int] | None = None
            if (
                float(max_val) >= threshold
                and abs(center[0] % tile_w - (tile_w >> 1)) <= allow_offset
                and abs(center[1] % tile_h - (tile_h >> 1)) <= allow_offset
            ):
                chosen_point = center
            else:
                half_w = tile_w >> 1
                im_l = im_gray[:, :half_w]
                im_r = im_gray[:, half_w:]
                _, val_l, _, loc_l = cv2.minMaxLoc(
                    cv2.matchTemplate(sheet_gray, im_l, cv2.TM_CCOEFF_NORMED)
                )
                _, val_r, _, loc_r = cv2.minMaxLoc(
                    cv2.matchTemplate(sheet_gray, im_r, cv2.TM_CCOEFF_NORMED)
                )
                p_l = (
                    round(loc_l[0] + im_l.shape[1] / 2),
                    round(loc_l[1] + im_l.shape[0] / 2),
                )
                p_r = (
                    round(loc_r[0] + im_r.shape[1] / 2),
                    round(loc_r[1] + im_r.shape[0] / 2),
                )
                find_l = (
                    float(val_l) >= threshold
                    and abs(p_l[0] % tile_w - tile_w / 4) <= allow_offset
                    and abs(p_l[1] % tile_h - (tile_h >> 1)) <= allow_offset
                )
                find_r = (
                    float(val_r) >= threshold
                    and min(
                        abs(p_r[0] % tile_w - tile_w / 4),
                        abs(p_r[0] % tile_w - 3 * tile_w / 4),
                    )
                    <= allow_offset
                    and abs(p_r[1] % tile_h - (tile_h >> 1)) <= allow_offset
                )
                if find_l and find_r:
                    chosen_point = p_l if float(val_l) > float(val_r) else p_r
                elif find_l:
                    chosen_point = p_l
                elif find_r:
                    chosen_point = p_r
                else:
                    if final_attempt and class_name == "Lancer":
                        raw_names[slot_index] = LANCER_FALLBACK_SERVANT
                        continue
                    found = False
                    break

            idx = STATUS_GRID_COLUMNS * int(chosen_point[1] // tile_h) + int(
                chosen_point[0] // tile_w
            )
            if 0 <= idx < len(class_entries) and isinstance(class_entries[idx], str):
                raw_names[slot_index] = class_entries[idx].split("_")[0]
            else:
                found = False
                break

        names = [name if isinstance(name, str) else None for name in raw_names]
        return {
            "classes": resolved_classes,
            "names": names,
            "raw_names": raw_names,
            "complete": bool(found),
        }

    def resolve_servant_metadata(
        self,
        server: str,
        name: str,
    ) -> dict[str, Any] | None:
        if not isinstance(name, str) or not name:
            return None
        catalog = self._load_servant_catalog(server)
        entry = catalog.get(name)
        if entry is None:
            return None
        canonical_name, details = entry
        sn = details.get("SN")
        np_color = details.get("NPcolor")
        servant_class = details.get("class")
        return {
            "name": name,
            "canonical_name": canonical_name,
            "class": servant_class if isinstance(servant_class, str) else None,
            "sn": str(sn) if isinstance(sn, (str, int)) else None,
            "np_color": np_color if isinstance(np_color, str) else None,
        }

    def apply_recognized_names(
        self,
        names: list[str | None] | tuple[str | None, ...],
        servant_positions: list[dict[str, Any] | None],
        *,
        occupied_positions: list[int | None] | None = None,
        party_servants: list[dict[str, Any]] | None = None,
        server: str = "CH",
    ) -> bool:
        changed = False
        candidates: list[dict[str, Any]] = []
        seen_slots: set[int] = set()
        for source in (party_servants or [], servant_positions):
            for entry in source:
                if not isinstance(entry, dict):
                    continue
                if not entry.get("name") and not entry.get("canonical_name"):
                    continue
                slot = entry.get("slot")
                if isinstance(slot, int) and not isinstance(slot, bool):
                    if slot in seen_slots:
                        continue
                    seen_slots.add(slot)
                candidates.append(dict(entry))

        for slot_index in range(min(3, len(names), len(servant_positions))):
            recognized_name = names[slot_index]
            if not isinstance(recognized_name, str) or not recognized_name:
                continue
            current = servant_positions[slot_index]
            if isinstance(current, dict) and (
                current.get("name") == recognized_name
                or current.get("canonical_name") == recognized_name
            ):
                if current.get("sn"):
                    continue

            matched_party = next(
                (
                    candidate
                    for candidate in candidates
                    if candidate.get("name") == recognized_name
                    or candidate.get("canonical_name") == recognized_name
                ),
                None,
            )
            if matched_party is not None:
                updated = dict(matched_party)
                if (
                    isinstance(current, dict)
                    and current.get("is_assist")
                    and not current.get("name")
                ):
                    updated["is_assist"] = True
                servant_positions[slot_index] = updated
                if occupied_positions is not None and slot_index < len(occupied_positions):
                    party_slot = updated.get("slot")
                    occupied_positions[slot_index] = (
                        party_slot
                        if isinstance(party_slot, int) and not isinstance(party_slot, bool)
                        else slot_index
                    )
                changed = True
                continue

            metadata = self.resolve_servant_metadata(server, recognized_name)
            new_slot = len(candidates) + slot_index
            preserved_slot = (
                current.get("slot")
                if isinstance(current, dict)
                and isinstance(current.get("slot"), int)
                and not isinstance(current.get("slot"), bool)
                else new_slot
            )
            updated = {
                "slot": preserved_slot,
                "name": recognized_name,
                "canonical_name": (
                    metadata["canonical_name"] if metadata is not None else recognized_name
                ),
                "class": metadata["class"] if metadata is not None else None,
                "active": True,
                "used": True,
                "sn": metadata["sn"] if metadata is not None else None,
                "np_color": metadata["np_color"] if metadata is not None else None,
            }
            if isinstance(current, dict) and (
                current.get("is_assist") or current.get("assist")
            ):
                updated["is_assist"] = True
            servant_positions[slot_index] = updated
            if occupied_positions is not None and slot_index < len(occupied_positions):
                occupied_positions[slot_index] = preserved_slot
            changed = True
        return changed

    @staticmethod
    def _validate_present(present: Any) -> None:
        if (
            not isinstance(present, (list, tuple))
            or len(present) != 3
            or any(type(flag) is not bool for flag in present)
        ):
            raise ValueError("present must contain exactly three booleans.")

    @staticmethod
    def _validate_threshold(value: Any, name: str) -> None:
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not 0 <= float(value) <= 1
        ):
            raise ValueError(f"{name} must be a number between 0 and 1.")

    @staticmethod
    def _decode_screenshot(screenshot: bytes):
        if cv2 is None or np is None:
            raise AppError(
                ErrorCode.OPENCV_UNAVAILABLE,
                "OpenCV and NumPy are required for frontline servant recognition.",
            )
        if not isinstance(screenshot, bytes) or not screenshot:
            raise ValueError("Screenshot image could not be decoded.")
        try:
            image = cv2.imdecode(
                np.frombuffer(screenshot, dtype=np.uint8),
                cv2.IMREAD_COLOR,
            )
        except cv2.error as exc:
            raise ValueError("Screenshot image could not be decoded.") from exc
        if image is None:
            raise ValueError("Screenshot image could not be decoded.")
        return image

    @staticmethod
    def _crop_scaled_rect(
        image: Any,
        rect_1080: tuple[int, int, int, int],
        scale_x: float,
        scale_y: float,
    ) -> Any:
        left = max(round(rect_1080[0] * scale_x), 0)
        top = max(round(rect_1080[1] * scale_y), 0)
        right = min(round(rect_1080[2] * scale_x), image.shape[1])
        bottom = min(round(rect_1080[3] * scale_y), image.shape[0])
        return image[top:bottom, left:right]

    def _load_class_icon_gray(self, class_name: str) -> Any:
        if class_name in self._class_icon_cache:
            return self._class_icon_cache[class_name]
        resources = self._resources
        if resources is None:
            return None
        try:
            path = resources.resolve_template(f"battle/public/classIcon/{class_name}.png")
        except AppError:
            return None
        image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        self._class_icon_cache[class_name] = image
        return image

    def _load_status_sheet_gray(self, class_name: str) -> Any:
        if class_name in self._status_sheet_cache:
            return self._status_sheet_cache[class_name]
        resources = self._resources
        if resources is None:
            return None
        try:
            path = resources.resolve_template(f"status/{class_name}.png")
        except AppError:
            return None
        image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        self._status_sheet_cache[class_name] = image
        return image

    def _load_status_info(self) -> dict[str, list[str]]:
        if self._status_info_cache is not None:
            return self._status_info_cache
        assets_dir = getattr(self._resources, "assets_dir", None)
        if not isinstance(assets_dir, Path):
            return {}
        info_path = assets_dir / "status" / "status_info.json"
        if not info_path.is_file():
            return {}
        try:
            data = json.loads(info_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(data, dict):
            return {}
        self._status_info_cache = data
        return data

    def _load_servant_catalog(
        self,
        server: str,
    ) -> dict[str, tuple[str, dict[str, Any]]]:
        normalized = server.upper() if isinstance(server, str) else "CH"
        if normalized in self._servant_catalog_cache:
            return self._servant_catalog_cache[normalized]
        data_dir = getattr(self._resources, "data_dir", None)
        if not isinstance(data_dir, Path):
            return {}
        candidates = (
            f"servant_info_{normalized}.json",
            "servant_info_jp.json" if normalized == "JP" else "servant_info.json",
        )
        path = next(
            (data_dir / filename for filename in candidates if (data_dir / filename).is_file()),
            None,
        )
        if path is None:
            return {}
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(raw, dict):
            return {}
        catalog: dict[str, tuple[str, dict[str, Any]]] = {}
        for canonical_name, details in raw.items():
            if not isinstance(details, dict):
                continue
            catalog[canonical_name] = (canonical_name, details)
            aliases = details.get("other_name")
            if isinstance(aliases, list):
                for alias in aliases:
                    if isinstance(alias, str):
                        catalog[alias] = (canonical_name, details)
        self._servant_catalog_cache[normalized] = catalog
        return catalog
