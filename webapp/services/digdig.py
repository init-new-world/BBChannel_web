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
_BOARD_TOOLS = ("shovel", "hammer", "pickaxe")
_TOOL_PIECES: dict[str, tuple[tuple[str, int], ...]] = {
    "shovel": (
        ("shovel_ash", 1),
        ("shovel_bone", 2),
        ("shovel_bullet", 3),
        ("shovel_arrow", 4),
        ("shovel_lantern", 5),
    ),
    "hammer": (
        ("hammer_teeth", 6),
        ("hammer_needle", 7),
        ("hammer_nail", 8),
        ("hammer_gear", 9),
        ("hammer_claw", 10),
    ),
    "pickaxe": (
        ("pickaxe_chain", 11),
        ("pickaxe_shield", 12),
        ("pickaxe_CSF", 13),
        ("pickaxe_steel", 14),
        ("pickaxe_blood", 15),
    ),
}
_EXTRA_MATERIALS = (
    ("hx", 1),
    ("jlg", 2),
    ("zsds", 3),
)
_PIECE_ID_BY_NAME: dict[str, int] = {
    name.lower(): piece_id
    for group in _TOOL_PIECES.values()
    for name, piece_id in group
} | {
    name.split("_", 1)[1].lower(): piece_id
    for group in _TOOL_PIECES.values()
    for name, piece_id in group
}
_EXTRA_ID_BY_NAME: dict[str, int] = {
    material.lower(): material_id for material, material_id in _EXTRA_MATERIALS
}
_BOARD_CELL_ROIS = tuple(
    (
        round((926 + column * 131) * 2 / 3),
        round((375 + row * 130) * 2 / 3),
        round((1057 + column * 131) * 2 / 3)
        - round((926 + column * 131) * 2 / 3),
        round((505 + row * 130) * 2 / 3)
        - round((375 + row * 130) * 2 / 3),
    )
    for row in range(4)
    for column in range(7)
)
_CROSS_ROIS = tuple(
    (
        round((991 + column * 131) * 2 / 3),
        round((440 + row * 130) * 2 / 3),
        round((1123 + column * 131) * 2 / 3)
        - round((991 + column * 131) * 2 / 3),
        round((570 + row * 130) * 2 / 3)
        - round((440 + row * 130) * 2 / 3),
    )
    for row in range(3)
    for column in range(6)
)


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

    def recognize_board_grid(
        self,
        screenshot: bytes,
        server: str,
        *,
        threshold: float = 0.7,
    ) -> dict[str, Any]:
        normalized_server = server.strip().upper()
        if normalized_server not in {"CH", "CNTW"}:
            raise ValueError("server must be CH or CNTW.")
        if not 0 <= threshold <= 1:
            raise ValueError("threshold must be between 0 and 1.")

        root = f"digdig/{normalized_server}"
        page = self._resources.template_index(prefix=root, limit=100)
        available_paths = {str(entry["path"]) for entry in page["entries"]}
        tool_paths = {
            tool: f"{root}/{tool}.png"
            for tool in _BOARD_TOOLS
            if f"{root}/{tool}.png" in available_paths
        }
        piece_paths = {
            tool: [
                (name, piece_id, f"{root}/{name}.png")
                for name, piece_id in _TOOL_PIECES[tool]
                if f"{root}/{name}.png" in available_paths
            ]
            for tool in _BOARD_TOOLS
        }
        extra_paths = {
            phase: [
                (material, material_id, f"{root}/{material}{phase}.png")
                for material, material_id in _EXTRA_MATERIALS
                if f"{root}/{material}{phase}.png" in available_paths
            ]
            for phase in range(4)
        }
        available_template_count = (
            len(tool_paths)
            + sum(len(items) for items in piece_paths.values())
            + sum(len(items) for items in extra_paths.values())
        )

        tool_specs = [
            (slot, tool, roi, tool_paths[tool])
            for slot, roi in enumerate(_BOARD_CELL_ROIS)
            for tool in _BOARD_TOOLS
            if tool in tool_paths
        ]
        tool_candidates = [
            {
                "template_path": template_path,
                "threshold": threshold,
                "roi": roi,
                "scales": _PIECE_SCALES,
            }
            for _slot, _tool, roi, template_path in tool_specs
        ]
        tool_results = (
            self._recognition.match_templates(screenshot, tool_candidates)
            if tool_candidates
            else []
        )
        best_tool_by_slot: dict[int, tuple[str, Any]] = {}
        for result, (slot, tool, _roi, _template_path) in zip(
            tool_results,
            tool_specs,
            strict=True,
        ):
            if not result.matched:
                continue
            current = best_tool_by_slot.get(slot)
            if current is None or result.confidence > current[1].confidence:
                best_tool_by_slot[slot] = (tool, result)

        dug_slot_set = (
            {
                slot
                for slot in range(len(_BOARD_CELL_ROIS))
                if slot not in best_tool_by_slot
            }
            if tool_paths
            else set()
        )

        piece_specs = [
            (slot, piece_name, piece_id, _BOARD_CELL_ROIS[slot], template_path)
            for slot, (tool, _tool_match) in sorted(best_tool_by_slot.items())
            for piece_name, piece_id, template_path in piece_paths[tool]
        ]
        intersection_meta = []
        cross_specs = []
        for index, roi in enumerate(_CROSS_ROIS):
            top_left = index + index // 6
            surrounding = [
                top_left,
                top_left + 1,
                top_left + 7,
                top_left + 8,
            ]
            dug_slots = [slot for slot in surrounding if slot in dug_slot_set]
            undug_slots = [
                slot for slot in surrounding if slot not in dug_slot_set
            ]
            phase = (
                surrounding.index(dug_slots[0])
                if 0 < len(dug_slots) < 4
                else None
            )
            probe_slot = surrounding[3] if len(dug_slots) == 0 else None
            intersection_meta.append(
                (
                    index,
                    roi,
                    surrounding,
                    dug_slots,
                    undug_slots,
                    phase,
                    probe_slot,
                )
            )
            if phase is not None:
                for material, material_id, template_path in extra_paths[phase]:
                    cross_specs.append(
                        (index, material, material_id, phase, roi, template_path)
                    )

        detail_candidates = [
            {
                "template_path": template_path,
                "threshold": threshold,
                "roi": roi,
                "scales": _PIECE_SCALES,
            }
            for _slot, _name, _piece_id, roi, template_path in piece_specs
        ] + [
            {
                "template_path": template_path,
                "threshold": threshold,
                "roi": roi,
                "scales": _PIECE_SCALES,
            }
            for (
                _index,
                _material,
                _material_id,
                _phase,
                roi,
                template_path,
            ) in cross_specs
        ]
        detail_results = (
            self._recognition.match_templates(screenshot, detail_candidates)
            if detail_candidates
            else []
        )
        piece_results = detail_results[: len(piece_specs)]
        cross_results = detail_results[len(piece_specs) :]

        best_piece_by_slot: dict[int, tuple[str, int, Any]] = {}
        for result, (slot, piece_name, piece_id, _roi, _template_path) in zip(
            piece_results,
            piece_specs,
            strict=True,
        ):
            if not result.matched:
                continue
            current = best_piece_by_slot.get(slot)
            if current is None or result.confidence > current[2].confidence:
                best_piece_by_slot[slot] = (piece_name, piece_id, result)

        best_cross_by_index: dict[int, tuple[str, int, Any]] = {}
        for result, (
            index,
            material,
            material_id,
            _phase,
            _roi,
            _template_path,
        ) in zip(
            cross_results,
            cross_specs,
            strict=True,
        ):
            if not result.matched:
                continue
            current = best_cross_by_index.get(index)
            if current is None or result.confidence > current[2].confidence:
                best_cross_by_index[index] = (material, material_id, result)

        slots = []
        for slot, roi in enumerate(_BOARD_CELL_ROIS):
            x, y, width, height = roi
            tool_match = best_tool_by_slot.get(slot)
            piece_match = best_piece_by_slot.get(slot)
            primary_match = (
                piece_match[2]
                if piece_match is not None
                else tool_match[1] if tool_match is not None else None
            )
            slots.append(
                {
                    "slot": slot,
                    "row": slot // 7,
                    "column": slot % 7,
                    "roi": list(roi),
                    "center": [x + width // 2, y + height // 2],
                    "dug": slot in dug_slot_set,
                    "tool": tool_match[0] if tool_match is not None else None,
                    "tool_confidence": (
                        tool_match[1].confidence
                        if tool_match is not None
                        else None
                    ),
                    "piece": (
                        piece_match[0] if piece_match is not None else None
                    ),
                    "piece_id": (
                        piece_match[1] if piece_match is not None else None
                    ),
                    "piece_confidence": (
                        piece_match[2].confidence
                        if piece_match is not None
                        else None
                    ),
                    "match": (
                        primary_match.to_dict()
                        if primary_match is not None
                        else None
                    ),
                }
            )

        intersections = []
        for (
            index,
            roi,
            surrounding,
            dug_slots,
            undug_slots,
            phase,
            probe_slot,
        ) in intersection_meta:
            x, y, width, height = roi
            cross_match = best_cross_by_index.get(index)
            intersections.append(
                {
                    "index": index,
                    "row": index // 6,
                    "column": index % 6,
                    "roi": list(roi),
                    "center": [x + width // 2, y + height // 2],
                    "surrounding_slots": surrounding,
                    "dug_slots": dug_slots,
                    "undug_slots": undug_slots,
                    "phase": phase,
                    "probe_slot": probe_slot,
                    "material": (
                        cross_match[0] if cross_match is not None else None
                    ),
                    "material_id": (
                        cross_match[1] if cross_match is not None else None
                    ),
                    "confidence": (
                        cross_match[2].confidence
                        if cross_match is not None
                        else None
                    ),
                    "match": (
                        cross_match[2].to_dict()
                        if cross_match is not None
                        else None
                    ),
                }
            )

        return {
            "server": normalized_server,
            "rows": 4,
            "columns": 7,
            "available_template_count": available_template_count,
            "candidate_count": len(tool_candidates) + len(detail_candidates),
            "recognized_tool_count": len(best_tool_by_slot),
            "recognized_piece_count": len(best_piece_by_slot),
            "recognized_intersection_count": len(best_cross_by_index),
            "dug_count": len(dug_slot_set),
            "slots": slots,
            "intersections": intersections,
        }

    @staticmethod
    def board_cell_roi(slot: int) -> tuple[int, int, int, int]:
        if isinstance(slot, bool) or not isinstance(slot, int) or not 0 <= slot < len(_BOARD_CELL_ROIS):
            raise ValueError(f"slot must be between 0 and {len(_BOARD_CELL_ROIS) - 1}.")
        return _BOARD_CELL_ROIS[slot]


def normalize_digdig_piece_targets(values: Any) -> list[int]:
    if values is None:
        return []
    if not isinstance(values, list):
        raise ValueError("target_pieces must be a list.")
    piece_ids: set[int] = set()
    for item in values:
        if isinstance(item, bool):
            raise ValueError("target_pieces entries must be piece names or IDs 1..15.")
        if isinstance(item, int):
            if not 1 <= item <= 15:
                raise ValueError("target_pieces integer IDs must be between 1 and 15.")
            piece_ids.add(item)
            continue
        if isinstance(item, str):
            key = item.strip().lower()
            piece_id = _PIECE_ID_BY_NAME.get(key)
            if piece_id is not None:
                piece_ids.add(piece_id)
                continue
        raise ValueError(f"Unknown excavation piece target: {item!r}.")
    return sorted(piece_ids)


def normalize_digdig_extra_targets(values: Any) -> list[int]:
    if values is None:
        return []
    if not isinstance(values, list):
        raise ValueError("target_extras must be a list.")
    extra_ids: set[int] = set()
    for item in values:
        if isinstance(item, bool):
            raise ValueError("target_extras entries must be material names or IDs 1..3.")
        if isinstance(item, int):
            if not 1 <= item <= 3:
                raise ValueError("target_extras integer IDs must be between 1 and 3.")
            extra_ids.add(item)
            continue
        if isinstance(item, str):
            key = item.strip().lower()
            extra_id = _EXTRA_ID_BY_NAME.get(key)
            if extra_id is not None:
                extra_ids.add(extra_id)
                continue
        raise ValueError(f"Unknown excavation extra material target: {item!r}.")
    return sorted(extra_ids)


def _piece_tool(name: str) -> str | None:
    for tool in ("hammer", "pickaxe", "shovel"):
        if name.startswith(f"{tool}_"):
            return tool
    return None
