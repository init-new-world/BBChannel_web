from __future__ import annotations

from typing import Any

from webapp.services.recognition import RecognitionService
from webapp.services.resources import ResourceService


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
