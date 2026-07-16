from __future__ import annotations

from typing import Any

from webapp.services.recognition import RecognitionService
from webapp.services.resources import ResourceService


TEAM_TEMPLATE_SCALES = (1.0, 0.75, 2 / 3, 0.5)
TEAM_LAYOUT_SCALE = 2 / 3


class TeamRecognizer:
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
        plan: dict[str, Any],
        *,
        threshold: float = 0.85,
    ) -> dict[str, Any]:
        servants = [
            self._recognize_servant(screenshot, servant, threshold)
            for servant in plan.get("servants", [])
            if isinstance(servant, dict)
        ]
        master = self._recognize_master(
            screenshot,
            plan.get("master"),
            threshold,
        )
        results = [*servants, master]
        mismatch_count = sum(result["status"] == "mismatch" for result in results)
        unverified_count = sum(result["status"] == "unverified" for result in results)
        return {
            "ok": mismatch_count == 0 and unverified_count == 0,
            "mismatch_count": mismatch_count,
            "unverified_count": unverified_count,
            "servants": servants,
            "master": master,
        }

    def _recognize_servant(
        self,
        screenshot: bytes,
        servant: dict[str, Any],
        threshold: float,
    ) -> dict[str, Any]:
        slot = servant.get("slot")
        expected = servant.get("canonical_name")
        base = {
            "slot": slot,
            "expected": expected or servant.get("name"),
        }
        if not servant.get("used") or not servant.get("name"):
            return {**base, "status": "skipped"}
        if (
            not isinstance(slot, int)
            or isinstance(slot, bool)
            or not 0 <= slot < 6
            or not isinstance(expected, str)
            or not expected
        ):
            return {**base, "status": "unverified", "reason": "missing_metadata"}

        templates = self._named_templates("servantface", expected)
        if not templates:
            return {**base, "status": "unverified", "reason": "missing_templates"}
        return {
            **base,
            **self._match_templates(
                screenshot,
                templates,
                threshold,
                roi=self._servant_roi(slot),
            ),
        }

    def _recognize_master(
        self,
        screenshot: bytes,
        master: Any,
        threshold: float,
    ) -> dict[str, Any]:
        if not isinstance(master, dict) or master.get("equip") is None:
            return {"expected": None, "status": "skipped"}
        expected = master.get("name")
        base = {"expected": expected, "equip": master.get("equip")}
        if not isinstance(expected, str) or not expected:
            return {**base, "status": "unverified", "reason": "missing_metadata"}
        templates = self._named_templates("masterequip", expected)
        if not templates:
            return {**base, "status": "unverified", "reason": "missing_templates"}
        return {
            **base,
            **self._match_templates(screenshot, templates, threshold),
        }

    def _match_templates(
        self,
        screenshot: bytes,
        templates: list[str],
        threshold: float,
        *,
        roi: tuple[int, int, int, int] | None = None,
    ) -> dict[str, Any]:
        candidates = [
            {
                "template_path": template_path,
                "threshold": threshold,
                "scales": TEAM_TEMPLATE_SCALES,
                **({"roi": roi} if roi is not None else {}),
            }
            for template_path in templates
        ]
        results = self._recognition.match_templates(screenshot, candidates)
        best = max(results, key=lambda result: result.confidence)
        return {
            "status": "matched" if best.matched else "mismatch",
            "template_path": best.template_path,
            "confidence": best.confidence,
            "threshold": best.threshold,
        }

    def _named_templates(self, prefix: str, name: str) -> list[str]:
        entries = self._resources.template_index(
            prefix=prefix,
            query=name,
            limit=1000,
        )["entries"]
        filename_prefix = f"{name}_"
        return [
            str(entry["path"])
            for entry in entries
            if str(entry["path"]).rsplit("/", 1)[-1].startswith(filename_prefix)
        ]

    @staticmethod
    def _servant_roi(slot: int) -> tuple[int, int, int, int]:
        source_left = 56 + 300 * slot + 22 * (slot // 3)
        source_right = 356 + 300 * slot + 22 * (slot // 3)
        left = round(source_left * TEAM_LAYOUT_SCALE)
        top = round(260 * TEAM_LAYOUT_SCALE)
        right = round(source_right * TEAM_LAYOUT_SCALE)
        bottom = round(550 * TEAM_LAYOUT_SCALE)
        return left, top, right - left, bottom - top
