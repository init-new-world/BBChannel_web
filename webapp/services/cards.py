from __future__ import annotations

from typing import Any

from webapp.services.recognition import RecognitionService
from webapp.services.resources import ResourceService


CARD_SLOT_ROIS = tuple((slot * 256, 340, 256, 330) for slot in range(5))
CARD_ORIGIN_X = (60, 444, 826, 1212, 1601)
CARD_STATUS_ROIS = tuple(
    (round((left + 210) / 1.5), 473, 53, 60)
    for left in CARD_ORIGIN_X
)
CARD_BLOCK_TEMPLATES = {"immobilized": "freeze.png", "sealed": "bjfy.png"}
STAR_SLOT_ROIS = (
    (73, 353, 47, 50),
    (329, 353, 47, 50),
    (584, 353, 47, 50),
    (841, 353, 47, 50),
    (1101, 353, 47, 50),
)
CARD_TEMPLATE_SCALES = (1.0, 0.75, 2 / 3, 0.5)
COLOR_TEMPLATES = {
    "B": "Buster.png",
    "A": "Arts.png",
    "Q": "Quick.png",
}


class CommandCardRecognizer:
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
        servants: list[dict[str, Any]],
        *,
        threshold: float = 0.7,
        special_keys: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        normalized_server = server.upper()
        if normalized_server not in {"CH", "CNTW", "JP"}:
            raise ValueError(f"Unsupported server: {server}")
        if not 0 <= threshold <= 1:
            raise ValueError("threshold must be between 0 and 1.")

        active_servants = [servant for servant in servants if servant.get("active") and servant.get("sn")]
        if not active_servants:
            active_servants = [servant for servant in servants if servant.get("sn")][:3]
        active_servants = active_servants[:3]

        servant_templates: list[tuple[int, dict[str, Any], str]] = []
        for default_position, servant in enumerate(active_servants, start=1):
            position = servant.get("battle_position", default_position)
            if (
                isinstance(position, bool)
                or not isinstance(position, int)
                or not 1 <= position <= 3
            ):
                position = default_position
            prefix = f"commands_{normalized_server}/{servant['sn']}"
            page = self._resources.template_index(prefix=prefix, limit=1000)
            for entry in page["entries"]:
                template_path = str(entry["path"])
                filename = template_path.rsplit("/", 1)[-1]
                if filename.startswith("card_servant_") and filename != "card_servant_np.png":
                    servant_templates.append((position, servant, template_path))

        candidates: list[dict[str, object]] = []
        candidate_meta: list[tuple[str, int, Any]] = []
        for slot_index, roi in enumerate(CARD_SLOT_ROIS):
            # Near-opaque text PNGs need centered correlation to reject portrait colors.
            for reason, filename in CARD_BLOCK_TEMPLATES.items():
                candidates.append({
                    "template_path": f"battle/{normalized_server}/{filename}",
                    "threshold": max(0.85, threshold), "roi": CARD_STATUS_ROIS[slot_index],
                    "scales": CARD_TEMPLATE_SCALES,
                    "centered_mask": True,
                })
                candidate_meta.append(("blocked", slot_index, reason))
            for color, filename in COLOR_TEMPLATES.items():
                candidates.append(
                    {
                        "template_path": f"battle/{normalized_server}/{filename}",
                        "threshold": threshold,
                        "roi": roi,
                        "scales": CARD_TEMPLATE_SCALES,
                    }
                )
                candidate_meta.append(("color", slot_index, color))
            for position, servant, template_path in servant_templates:
                candidates.append(
                    {
                        "template_path": template_path,
                        "threshold": threshold,
                        "roi": roi,
                        "scales": CARD_TEMPLATE_SCALES,
                    }
                )
                candidate_meta.append(
                    (
                        "servant",
                        slot_index,
                        {
                            "position": position,
                            "name": servant.get("name"),
                            "sn": str(servant["sn"]),
                        },
                    )
                )
            for special_key in special_keys or []:
                template_path = special_key.get("template_path")
                code = special_key.get("code")
                special_threshold = special_key.get("threshold", threshold)
                if not isinstance(template_path, str) or not isinstance(code, str):
                    raise ValueError("Special key template_path and code must be strings.")
                if (
                    isinstance(special_threshold, bool)
                    or not isinstance(special_threshold, (int, float))
                    or not 0 <= special_threshold <= 1
                ):
                    raise ValueError("Special key threshold must be between 0 and 1.")
                search_region = _special_key_search_region(special_key, slot_index)
                if search_region is None:
                    continue
                special_roi, special_scales = search_region
                candidates.append(
                    {
                        "template_path": template_path,
                        "threshold": float(special_threshold),
                        "roi": special_roi,
                        "scales": special_scales,
                    }
                )
                candidate_meta.append(("special", slot_index, code))
            star_roi = STAR_SLOT_ROIS[slot_index]
            for template_number in range(10):
                candidates.append(
                    {
                        "template_path": f"battle/public/starNum/n{template_number}.png",
                        "mask_path": f"battle/public/starNum/n{template_number}mask.png",
                        "threshold": 0.7,
                        "roi": star_roi,
                    }
                )
                candidate_meta.append(
                    ("star", slot_index, 10 if template_number == 0 else template_number)
                )

        matches = self._recognition.match_templates(screenshot, candidates)
        grouped: list[dict[str, list[tuple[Any, Any]]]] = [
            {"color": [], "servant": [], "star": [], "special": [], "blocked": []}
            for _ in CARD_SLOT_ROIS
        ]
        for meta, match in zip(candidate_meta, matches, strict=True):
            kind, slot_index, value = meta
            grouped[slot_index][kind].append((value, match))

        cards = []
        for slot_index, groups in enumerate(grouped):
            color_value, color_match = _best_match(groups["color"])
            servant_value, servant_match = _best_match(groups["servant"])
            star_value, star_match = _best_match(groups["star"])
            blocked_reason, blocked_match = _best_match(groups["blocked"])
            special_matches = [
                (value, match)
                for value, match in groups["special"]
                if match.matched
            ]
            recognized = color_match is not None and servant_match is not None and blocked_match is None
            cards.append(
                {
                    "slot": slot_index + 1,
                    "available": recognized,
                    "blocked_reason": blocked_reason if blocked_match is not None else None,
                    "blocked_confidence": blocked_match.confidence if blocked_match is not None else None,
                    "code": (
                        f"{servant_value['position']}{color_value}" if recognized else None
                    ),
                    "color": color_value if color_match is not None else None,
                    "servant_position": (
                        servant_value["position"] if servant_match is not None else None
                    ),
                    "servant_name": (
                        servant_value["name"] if servant_match is not None else None
                    ),
                    "servant_sn": servant_value["sn"] if servant_match is not None else None,
                    "stars": star_value if star_match is not None else 0,
                    "special_keys": [value for value, _match in special_matches],
                    "special_key_confidences": {
                        value: match.confidence for value, match in special_matches
                    },
                    "color_confidence": (
                        color_match.confidence if color_match is not None else None
                    ),
                    "servant_confidence": (
                        servant_match.confidence if servant_match is not None else None
                    ),
                    "star_confidence": (
                        star_match.confidence if star_match is not None else None
                    ),
                    "color_template": (
                        color_match.template_path if color_match is not None else None
                    ),
                    "servant_template": (
                        servant_match.template_path if servant_match is not None else None
                    ),
                    "star_template": (
                        star_match.template_path if star_match is not None else None
                    ),
                }
            )

        recognized_count = sum(card["code"] is not None for card in cards)
        blocked_count = sum(card["blocked_reason"] is not None for card in cards)
        return {
            "server": normalized_server,
            "cards": cards,
            "recognized_count": recognized_count,
            "available_count": sum(card["available"] for card in cards),
            "complete": recognized_count + blocked_count == len(CARD_SLOT_ROIS),
        }


def _best_match(candidates: list[tuple[Any, Any]]) -> tuple[Any, Any | None]:
    matched = [(value, result) for value, result in candidates if result.matched]
    if not matched:
        return None, None
    return max(matched, key=lambda item: item[1].confidence)


def _special_key_search_region(
    key: dict[str, Any], slot_index: int,
) -> tuple[tuple[int, int, int, int], tuple[float, ...]] | None:
    fields = ("source_width", "source_height", "left", "right", "top", "bottom")
    if not any(field in key for field in fields):
        return CARD_SLOT_ROIS[slot_index], CARD_TEMPLATE_SCALES
    values = [key.get(field) for field in fields]
    if any(isinstance(value, bool) or not isinstance(value, int) for value in values):
        raise ValueError("Special key metadata must contain integer source dimensions and bounds.")
    width, height, left, right, top, bottom = values
    if width <= 0 or height <= 0 or left >= right or top >= bottom:
        raise ValueError("Special key metadata has invalid source dimensions or bounds.")

    # Legacy metadata is relative to a 290x390 card, with animation tolerance.
    source_scale = min(width / 1920, height / 1080)
    scene_scale = 2 / 3
    template_width = max(round((right - left) * scene_scale / source_scale), 1)
    template_height = max(round((bottom - top) * scene_scale / source_scale), 1)
    left = max(round(left / source_scale) - 13, 0)
    right = min(round(right / source_scale) + 13, 290)
    top = max(round(top / source_scale - 40) - 13, 0)
    bottom = min(round(bottom / source_scale + 40) + 13, 390)
    if left >= right or top >= bottom:
        return None
    origin_x = CARD_ORIGIN_X[slot_index]
    x0, x1 = (round((origin_x + value) * scene_scale) for value in (left, right))
    y0, y1 = (round((530 + value) * scene_scale) for value in (top, bottom))
    if template_width > x1 - x0 or template_height > y1 - y0:
        return None
    return (x0, y0, x1 - x0, y1 - y0), (scene_scale / source_scale,)
