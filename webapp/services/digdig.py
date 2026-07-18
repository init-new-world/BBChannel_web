from __future__ import annotations

from typing import Any

from webapp.services.recognition import RecognitionService
from webapp.services.resources import ResourceService


_STATE_SPECS = (
    ("execute", "actionable", "execute_dig"),
    ("digResult", "observed", None),
    ("freeDig", "observed", None),
    ("needConfirm", "observed", None),
    ("reward", "observed", None),
    ("checkmark", "observed", None),
    ("corner", "observed", None),
    ("hammer", "observed", None),
    ("pickaxe", "observed", None),
    ("shovel", "observed", None),
)
_PIECE_NAMES = (
    "hammer_claw",
    "hammer_gear",
    "hammer_nail",
    "hammer_needle",
    "hammer_teeth",
    "pickaxe_CSF",
    "pickaxe_blood",
    "pickaxe_chain",
    "pickaxe_shield",
    "pickaxe_steel",
    "shovel_arrow",
    "shovel_ash",
    "shovel_bone",
    "shovel_bullet",
    "shovel_lantern",
    "hx0",
    "hx1",
    "hx2",
    "hx3",
    "jlg0",
    "jlg1",
    "jlg2",
    "jlg3",
    "zsds0",
    "zsds1",
    "zsds2",
    "zsds3",
)
_STATE_SCALES = (1.0, 0.75, 2 / 3, 0.5)
_PIECE_SCALES = (2 / 3,)


class DigdigRecognizer:
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
        if normalized_server not in {"CH", "CNTW"}:
            raise ValueError("server must be CH or CNTW.")
        if not 0 <= threshold <= 1:
            raise ValueError("threshold must be between 0 and 1.")

        root = f"digdig/{normalized_server}"
        page = self._resources.template_index(prefix=root, limit=100)
        available_paths = {str(entry["path"]) for entry in page["entries"]}
        specs = [
            {
                "kind": "state",
                "name": name,
                "status": status,
                "recommended_action": action,
                "template_path": f"{root}/{name}.png",
                "scales": _STATE_SCALES,
            }
            for name, status, action in _STATE_SPECS
            if f"{root}/{name}.png" in available_paths
        ]
        specs.extend(
            {
                "kind": "piece",
                "name": name,
                "tool": _piece_tool(name),
                "template_path": f"{root}/{name}.png",
                "scales": _PIECE_SCALES,
            }
            for name in _PIECE_NAMES
            if f"{root}/{name}.png" in available_paths
        )
        candidates = [
            {
                "template_path": spec["template_path"],
                "threshold": threshold,
                "scales": spec["scales"],
            }
            for spec in specs
        ]
        results = (
            self._recognition.match_templates(screenshot, candidates)
            if candidates
            else []
        )
        matches = []
        pieces = []
        for result, spec in zip(results, specs, strict=True):
            if not result.matched:
                continue
            item = {
                "name": spec["name"],
                **result.to_dict(),
            }
            if spec["kind"] == "piece":
                pieces.append({"tool": spec["tool"], **item})
            else:
                matches.append(
                    {
                        "status": spec["status"],
                        "recommended_action": spec["recommended_action"],
                        **item,
                    }
                )

        primary = matches[0] if matches else None
        if primary is None and pieces:
            state = "board"
            status = "observed"
        else:
            state = primary["name"] if primary else "unknown"
            status = primary["status"] if primary else "unknown"
        suggested_tool = next(
            (piece["tool"] for piece in pieces if piece["tool"] is not None),
            None,
        )
        return {
            "server": normalized_server,
            "state": state,
            "status": status,
            "recommended_action": (
                primary["recommended_action"] if primary else None
            ),
            "available_template_count": len(candidates),
            "matches": matches,
            "pieces": pieces,
            "suggested_tool": suggested_tool,
        }


def _piece_tool(name: str) -> str | None:
    for tool in ("hammer", "pickaxe", "shovel"):
        if name.startswith(f"{tool}_"):
            return tool
    return None
