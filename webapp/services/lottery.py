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
