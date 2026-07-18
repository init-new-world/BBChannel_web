from __future__ import annotations

from typing import Any

from webapp.services.recognition import RecognitionService
from webapp.services.resources import ResourceService


CHOCOLATE_SCALES = (1.0, 0.75, 2 / 3, 0.5)
_STATE_SPECS = (
    ("limit", "blocked", "storage_full", None),
    ("notEnough", "blocked", "materials_exhausted", None),
    ("yes", "actionable", None, "confirm"),
    ("decide", "actionable", None, "decide"),
    ("receive_all_on", "actionable", None, "receive_all"),
    ("receive", "actionable", None, "receive"),
    ("exchange", "actionable", None, "exchange"),
    ("makeChoco", "actionable", None, "make_chocolate"),
    ("randChoco", "actionable", None, "select_random_chocolate"),
    ("end", "actionable", None, "continue_exchange"),
    ("choosePay", "actionable", None, "close_reward_filter"),
    ("someone", "actionable", None, "close_dialog"),
    ("x", "actionable", None, "close_dialog"),
    ("receive_all_off", "observed", None, None),
    ("equipExp_on", "observed", None, None),
    ("equipExp_off", "observed", None, None),
    ("giftbox_loaded", "observed", None, None),
    ("in_box", "observed", None, None),
    ("pay", "observed", None, None),
    ("skip", "observed", None, None),
    ("valentino", "observed", None, None),
    ("10", "observed", None, None),
)


class ChocolateRecognizer:
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
        threshold: float = 0.82,
    ) -> dict[str, Any]:
        normalized_server = server.strip().upper()
        if normalized_server not in {"CH", "CNTW", "JP"}:
            raise ValueError("server must be CH, CNTW, or JP.")
        if not 0 <= threshold <= 1:
            raise ValueError("threshold must be between 0 and 1.")

        root = f"chocolate/{normalized_server}"
        page = self._resources.template_index(prefix=root, limit=100)
        available_paths = {str(entry["path"]) for entry in page["entries"]}
        available_specs = [
            (name, status, reason, action, f"{root}/{name}.png")
            for name, status, reason, action in _STATE_SPECS
            if f"{root}/{name}.png" in available_paths
        ]
        candidates = [
            {
                "template_path": template_path,
                "threshold": threshold,
                "scales": CHOCOLATE_SCALES,
            }
            for _name, _status, _reason, _action, template_path in available_specs
        ]
        results = (
            self._recognition.match_templates(screenshot, candidates)
            if candidates
            else []
        )
        matches = [
            {
                "name": name,
                "status": status,
                "reason": reason,
                "recommended_action": action,
                **match.to_dict(),
            }
            for match, (name, status, reason, action, _template_path) in zip(
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
            "status": primary["status"] if primary else "unknown",
            "reason": primary["reason"] if primary else None,
            "recommended_action": (
                primary["recommended_action"] if primary else None
            ),
            "available_template_count": len(candidates),
            "matches": matches,
        }
