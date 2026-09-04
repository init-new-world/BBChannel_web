from __future__ import annotations

import json
from pathlib import Path
from threading import RLock
from typing import Any

from webapp.core.errors import AppError, ErrorCode


SERVER_ORDER = ("CH", "CNTW", "JP")


class MaterialDropService:
    def __init__(self, data_dir: Path | str) -> None:
        self._data_dir = Path(data_dir)
        self._lock = RLock()

    def catalog(self) -> dict[str, object]:
        with self._lock:
            qualities, information = self._load_data()
            return {
                "servers": sorted(
                    information,
                    key=lambda server: (
                        SERVER_ORDER.index(server) if server in SERVER_ORDER else len(SERVER_ORDER),
                        server,
                    ),
                ),
                "qualities": [
                    {"name": quality, "materials": list(materials)}
                    for quality, materials in qualities.items()
                ],
            }

    def query(self, server: str, quality: str, material: str) -> dict[str, object]:
        normalized_server = server.strip().upper()
        normalized_quality = quality.strip()
        normalized_material = material.strip()
        with self._lock:
            qualities, information = self._load_data()
            if normalized_server not in information:
                raise _invalid_filter("server", server, list(information))
            materials = qualities.get(normalized_quality)
            if materials is None:
                raise _invalid_filter("quality", quality, list(qualities))
            if normalized_material not in materials:
                raise _invalid_filter("material", material, materials)
            raw_stages = (
                information.get(normalized_server, {})
                .get(normalized_quality, {})
                .get(normalized_material, [])
            )
            if not isinstance(raw_stages, list):
                raise AppError(
                    ErrorCode.DATA_FILE_INVALID,
                    "Material drop data has an invalid stage list.",
                    {
                        "server": normalized_server,
                        "quality": normalized_quality,
                        "material": normalized_material,
                    },
                )
            stages = [_normalize_stage(stage) for stage in raw_stages]
            stages.sort(key=lambda stage: (stage["average_ap"], stage["chapter"], stage["section"]))
            return {
                "server": normalized_server,
                "quality": normalized_quality,
                "material": normalized_material,
                "count": len(stages),
                "stages": stages,
            }

    def _load_data(self) -> tuple[dict[str, list[str]], dict[str, Any]]:
        qualities = _read_json(self._data_dir / "material_quality.json")
        information = _read_json(self._data_dir / "material_info.json")
        if not isinstance(qualities, dict) or not all(
            isinstance(quality, str)
            and isinstance(materials, list)
            and all(isinstance(material, str) for material in materials)
            for quality, materials in qualities.items()
        ):
            raise AppError(
                ErrorCode.DATA_FILE_INVALID,
                "Material quality data has an invalid structure.",
            )
        if not isinstance(information, dict) or not all(
            isinstance(server, str) and isinstance(values, dict)
            for server, values in information.items()
        ):
            raise AppError(
                ErrorCode.DATA_FILE_INVALID,
                "Material drop data has an invalid structure.",
            )
        return qualities, information


def _read_json(path: Path) -> object:
    if not path.is_file():
        raise AppError(
            ErrorCode.DATA_FILE_NOT_FOUND,
            f"Material data file was not found: {path.name}",
            {"path": str(path)},
        )
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AppError(
            ErrorCode.DATA_FILE_INVALID,
            f"Material data file could not be loaded: {path.name}",
            {"path": str(path), "error": str(exc)},
        ) from exc


def _normalize_stage(stage: object) -> dict[str, object]:
    if not isinstance(stage, dict):
        raise AppError(
            ErrorCode.DATA_FILE_INVALID,
            "Material drop stage must be an object.",
        )
    chapter = stage.get("chapter")
    section = stage.get("section")
    average_ap = stage.get("AP")
    drop_rate = stage.get("P")
    if (
        not isinstance(chapter, str)
        or not isinstance(section, str)
        or isinstance(average_ap, bool)
        or not isinstance(average_ap, (int, float))
        or not isinstance(drop_rate, (str, int, float))
    ):
        raise AppError(
            ErrorCode.DATA_FILE_INVALID,
            "Material drop stage has invalid fields.",
            {"stage": stage},
        )
    drop_rate_text = str(drop_rate)
    try:
        drop_rate_percent = float(drop_rate_text.rstrip("%"))
    except ValueError as exc:
        raise AppError(
            ErrorCode.DATA_FILE_INVALID,
            "Material drop rate is invalid.",
            {"drop_rate": drop_rate_text},
        ) from exc
    return {
        "chapter": chapter.split("/", 1)[0],
        "section": section,
        "average_ap": float(average_ap),
        "drop_rate": drop_rate_text,
        "drop_rate_percent": drop_rate_percent,
    }


def _invalid_filter(field: str, value: str, allowed: list[str]) -> AppError:
    return AppError(
        ErrorCode.DATA_FILE_INVALID,
        f"Material {field} is invalid.",
        {"field": field, "value": value, "allowed": allowed},
    )
