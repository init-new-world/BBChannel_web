from __future__ import annotations

from typing import Any

from webapp.services.recognition import RecognitionService
from webapp.services.resources import ResourceService


_STATE_SPECS = (
    ("noSucai", "enhancement", "blocked", "materials_exhausted", None),
    ("no_servant", "enhancement", "blocked", "no_matching_target", None),
    ("callfree", "summon", "actionable", None, "summon_free_ten"),
    ("call10", "summon", "actionable", None, "summon_ten"),
    ("again10", "summon", "actionable", None, "summon_again"),
    ("again10_0", "summon", "actionable", None, "summon_again"),
    ("again10_1", "summon", "actionable", None, "summon_again"),
    ("boxfull", "summon", "actionable", None, "handle_full_box"),
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
    ("feedjd", "enhancement", "observed", None, None),
    ("doubleEXP", "enhancement", "observed", None, None),
    ("decide", "confirmation", "observed", None, None),
    ("sure", "confirmation", "observed", None, None),
    ("menu", "navigation", "observed", None, None),
    ("shop", "navigation", "observed", None, None),
)
_SCALES = (1.0, 0.75, 2 / 3, 0.5)

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
