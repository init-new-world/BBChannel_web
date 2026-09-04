from __future__ import annotations

import base64
import os
import tempfile
from io import BytesIO
from pathlib import Path
from threading import RLock

from PIL import Image, UnidentifiedImageError

from webapp.core.errors import AppError, ErrorCode
from webapp.core.models import MatchResult
from webapp.services.recognition import RecognitionService
from webapp.services.resources import ResourceService


TEMPLATE_SIZE = (237, 68)
CHECK_BOX = (194, 34, 228, 68)
MAIN_MATCH_BOX = (39, 0, 194, 56)
MATCH_SCALES = (1.0, 0.75, 2 / 3, 0.5)
INVALID_NAME_CHARACTERS = set('<>:"/\\|?*')
EXTRACTION_REFERENCE_SIZE = (1788, 1006)
EXTRACTION_REGIONS = (
    ("equip", (-110, 58, 110, 122)),
    ("skill_1", (127, -78, 347, -15)),
    ("skill_2", (127, -13, 347, 50)),
    ("skill_3", (127, 52, 347, 115)),
)


class EquipTemplateService:
    def __init__(
        self,
        resources: ResourceService,
        recognition: RecognitionService | None = None,
    ) -> None:
        self._resources = resources
        self._recognition = recognition or RecognitionService(resources)
        self._lock = RLock()
        assets = resources.assets_dir
        self._locations = {
            "active": (
                assets / "assist" / "assist_equip",
                assets / "assist" / "equip_check",
            ),
            "archive": (
                assets / "equipmaker" / "assist_equip_store",
                assets / "equipmaker" / "equip_check_store",
            ),
        }

    def inventory(self) -> list[dict[str, object]]:
        with self._lock:
            templates: list[dict[str, object]] = []
            for location in ("active", "archive"):
                image_dir, check_dir = self._locations[location]
                if not image_dir.exists():
                    continue
                for path in sorted(image_dir.glob("*.png"), key=lambda item: item.stem.casefold()):
                    if not path.is_file():
                        continue
                    templates.append(self._describe(path.stem, location, check_dir))
            return templates

    def build(
        self,
        name: str,
        *,
        full_image: bytes | None,
        non_full_image: bytes | None,
        overwrite: bool = False,
    ) -> dict[str, object]:
        normalized_name = _validate_name(name)
        if full_image is None and non_full_image is None:
            raise AppError(
                ErrorCode.DATA_FILE_INVALID,
                "At least one equip image is required.",
                {"name": normalized_name},
            )
        full = _load_image(full_image, "full_image_base64") if full_image is not None else None
        non_full = (
            _load_image(non_full_image, "non_full_image_base64")
            if non_full_image is not None
            else None
        )
        full = full.resize(TEMPLATE_SIZE, Image.Resampling.LANCZOS) if full is not None else None
        non_full = (
            non_full.resize(TEMPLATE_SIZE, Image.Resampling.LANCZOS)
            if non_full is not None
            else None
        )

        with self._lock:
            image_dir, check_dir = self._locations["archive"]
            image_dir.mkdir(parents=True, exist_ok=True)
            check_dir.mkdir(parents=True, exist_ok=True)
            image_path = image_dir / f"{normalized_name}.png"
            check_paths = [
                check_dir / f"{normalized_name}_0.png",
                check_dir / f"{normalized_name}_1.png",
            ]
            if image_path.exists() and not overwrite:
                raise AppError(
                    ErrorCode.DATA_FILE_CONFLICT,
                    f"Equip template already exists: {normalized_name}",
                    {"name": normalized_name, "location": "archive"},
                )

            _save_png_atomic(full or non_full, image_path)
            if full is not None and non_full is not None:
                _save_png_atomic(non_full.crop(CHECK_BOX), check_paths[0])
                _save_png_atomic(full.crop(CHECK_BOX), check_paths[1])
            else:
                for path in check_paths:
                    path.unlink(missing_ok=True)
            self._resources.refresh_template_index()
            return self._describe(normalized_name, "archive", check_dir)

    def activate(self, name: str, *, overwrite: bool = False) -> dict[str, object]:
        return self._move(name, source="archive", destination="active", overwrite=overwrite)

    def archive(self, name: str, *, overwrite: bool = False) -> dict[str, object]:
        return self._move(name, source="active", destination="archive", overwrite=overwrite)

    def read_image(self, name: str, *, location: str) -> bytes:
        normalized_name = _validate_name(name)
        if location not in self._locations:
            raise AppError(
                ErrorCode.DATA_FILE_INVALID,
                "Equip template location is invalid.",
                {"location": location},
            )
        with self._lock:
            image_dir, _check_dir = self._locations[location]
            image_path = image_dir / f"{normalized_name}.png"
            if not image_path.is_file():
                raise AppError(
                    ErrorCode.DATA_FILE_NOT_FOUND,
                    f"Equip template was not found in {location}: {normalized_name}",
                    {"name": normalized_name, "location": location},
                )
            return image_path.read_bytes()

    def extract_candidates(
        self,
        screenshot: bytes,
        anchors: list[list[int]],
    ) -> list[dict[str, object]]:
        image = _load_image(screenshot, "screenshot_base64")
        width, height = image.size
        reference_width, reference_height = EXTRACTION_REFERENCE_SIZE
        candidates: list[dict[str, object]] = []
        for row_index, anchor in enumerate(anchors[:20], start=1):
            if len(anchor) != 2:
                continue
            anchor_x, anchor_y = anchor
            adjusted_x = anchor_x + 10 * width / reference_width
            adjusted_y = anchor_y + 20 * height / reference_height
            for kind, offsets in EXTRACTION_REGIONS:
                left_offset, top_offset, right_offset, bottom_offset = offsets
                bounds = (
                    round(adjusted_x + left_offset * width / reference_width),
                    round(adjusted_y + top_offset * height / reference_height),
                    round(adjusted_x + right_offset * width / reference_width),
                    round(adjusted_y + bottom_offset * height / reference_height),
                )
                if not _box_inside(bounds, image.size):
                    continue
                candidate_image = image.crop(bounds).resize(
                    TEMPLATE_SIZE,
                    Image.Resampling.LANCZOS,
                )
                candidates.append(
                    {
                        "id": f"{row_index}:{kind}",
                        "row": row_index,
                        "kind": kind,
                        "bounds": list(bounds),
                        "image_base64": base64.b64encode(_encode_png(candidate_image)).decode(
                            "ascii"
                        ),
                    }
                )
        return candidates

    def test_template(
        self,
        name: str,
        *,
        location: str,
        screenshot: bytes,
        threshold: float = 0.9,
    ) -> dict[str, object]:
        normalized_name = _validate_name(name)
        if location not in self._locations:
            raise AppError(
                ErrorCode.DATA_FILE_INVALID,
                "Equip template location is invalid.",
                {"location": location},
            )
        screenshot_size = _load_image(screenshot, "screenshot_base64").size
        with self._lock:
            image_dir, check_dir = self._locations[location]
            image_path = image_dir / f"{normalized_name}.png"
            if not image_path.is_file():
                raise AppError(
                    ErrorCode.DATA_FILE_NOT_FOUND,
                    f"Equip template was not found in {location}: {normalized_name}",
                    {"name": normalized_name, "location": location},
                )
            relative_image_path = image_path.relative_to(self._resources.assets_dir).as_posix()
            precise = all(
                (check_dir / f"{normalized_name}_{flag}.png").is_file()
                for flag in (0, 1)
            )
            matches = self._recognition.match_template_all(
                screenshot,
                relative_image_path,
                threshold=threshold,
                scales=MATCH_SCALES,
                template_crop=MAIN_MATCH_BOX,
                max_results=20,
            )
            results = [self._test_match(match) for match in matches]
            valid_matches = [
                (index, match, result)
                for index, (match, result) in enumerate(zip(matches, results, strict=True))
                if _roi_inside(tuple(result["check_roi"]), screenshot_size)
            ]
            if precise and valid_matches:
                check_prefix = (
                    "assist/equip_check"
                    if location == "active"
                    else "equipmaker/equip_check_store"
                )
                check_requests = []
                for _index, match, result in valid_matches:
                    common = {
                        "threshold": 0.0,
                        "roi": result["check_roi"],
                        "scales": [match.scale],
                    }
                    check_requests.extend(
                        [
                            {
                                **common,
                                "template_path": f"{check_prefix}/{normalized_name}_0.png",
                            },
                            {
                                **common,
                                "template_path": f"{check_prefix}/{normalized_name}_1.png",
                            },
                        ]
                    )
                check_results = self._recognition.match_templates(screenshot, check_requests)
                for position, (index, _match, _result) in enumerate(valid_matches):
                    non_full = check_results[position * 2]
                    full = check_results[position * 2 + 1]
                    results[index].update(
                        {
                            "full_limit_break": full.confidence >= non_full.confidence,
                            "limit_break_method": "precise",
                            "limit_break_confidence": full.confidence,
                            "non_full_confidence": non_full.confidence,
                        }
                    )
            elif valid_matches:
                star_path = self._resources.assets_dir / "assist" / "equip_check" / "star.png"
                mask_path = self._resources.assets_dir / "assist" / "equip_check" / "starMask.png"
                if star_path.is_file():
                    marker_results = self._recognition.match_templates(
                        screenshot,
                        [
                            {
                                "template_path": "assist/equip_check/star.png",
                                "threshold": 0.8,
                                "roi": result["check_roi"],
                                "scales": [match.scale],
                                "mask_path": (
                                    "assist/equip_check/starMask.png"
                                    if mask_path.is_file()
                                    else None
                                ),
                            }
                            for _index, match, result in valid_matches
                        ],
                    )
                    for (index, _match, _result), marker in zip(
                        valid_matches,
                        marker_results,
                        strict=True,
                    ):
                        results[index].update(
                            {
                                "full_limit_break": marker.matched,
                                "limit_break_method": "star_marker",
                                "limit_break_confidence": marker.confidence,
                            }
                        )
            return {
                "name": normalized_name,
                "location": location,
                "precise": precise,
                "match_count": len(results),
                "matches": results,
            }

    def _test_match(
        self,
        match: MatchResult,
    ) -> dict[str, object]:
        scale = float(match.scale)
        check_roi = _check_roi(match.top_left, scale)
        return {
            "top_left": list(match.top_left),
            "size": list(match.size),
            "center": list(match.center),
            "confidence": float(match.confidence),
            "scale": scale,
            "check_roi": list(check_roi),
            "full_limit_break": None,
            "limit_break_method": "unavailable",
            "limit_break_confidence": None,
            "non_full_confidence": None,
        }

    def _move(
        self,
        name: str,
        *,
        source: str,
        destination: str,
        overwrite: bool,
    ) -> dict[str, object]:
        normalized_name = _validate_name(name)
        with self._lock:
            source_image_dir, source_check_dir = self._locations[source]
            destination_image_dir, destination_check_dir = self._locations[destination]
            source_image = source_image_dir / f"{normalized_name}.png"
            if not source_image.is_file():
                raise AppError(
                    ErrorCode.DATA_FILE_NOT_FOUND,
                    f"Equip template was not found in {source}: {normalized_name}",
                    {"name": normalized_name, "location": source},
                )

            destination_image = destination_image_dir / source_image.name
            destination_checks = [
                destination_check_dir / f"{normalized_name}{suffix}"
                for suffix in ("_0.png", "_1.png")
            ]
            pairs = [(source_image, destination_image)]
            for suffix in ("_0.png", "_1.png"):
                source_check = source_check_dir / f"{normalized_name}{suffix}"
                if source_check.is_file():
                    pairs.append((source_check, destination_check_dir / source_check.name))
            destination_files = [destination_image, *destination_checks]
            conflicts = [target for target in destination_files if target.exists()]
            if conflicts and not overwrite:
                raise AppError(
                    ErrorCode.DATA_FILE_CONFLICT,
                    f"Equip template already exists in {destination}: {normalized_name}",
                    {"name": normalized_name, "location": destination},
                )

            destination_image_dir.mkdir(parents=True, exist_ok=True)
            destination_check_dir.mkdir(parents=True, exist_ok=True)
            moved: list[tuple[Path, Path]] = []
            backups: list[tuple[Path, Path]] = []
            try:
                for destination_path in conflicts:
                    backup_path = _reserve_temporary_path(destination_path, suffix=".backup")
                    os.replace(destination_path, backup_path)
                    backups.append((destination_path, backup_path))
                for source_path, destination_path in pairs:
                    os.replace(source_path, destination_path)
                    moved.append((source_path, destination_path))
            except OSError as exc:
                for source_path, destination_path in reversed(moved):
                    if destination_path.exists() and not source_path.exists():
                        os.replace(destination_path, source_path)
                for destination_path, backup_path in reversed(backups):
                    if backup_path.exists():
                        os.replace(backup_path, destination_path)
                raise AppError(
                    ErrorCode.DATA_FILE_INVALID,
                    f"Equip template could not be moved to {destination}.",
                    {"name": normalized_name, "error": str(exc)},
                ) from exc
            finally:
                for _destination_path, backup_path in backups:
                    backup_path.unlink(missing_ok=True)

            self._resources.refresh_template_index()
            return self._describe(normalized_name, destination, destination_check_dir)

    def _describe(
        self,
        name: str,
        location: str,
        check_dir: Path,
    ) -> dict[str, object]:
        image_prefix = "assist/assist_equip" if location == "active" else "equipmaker/assist_equip_store"
        return {
            "name": name,
            "location": location,
            "precise": all((check_dir / f"{name}_{flag}.png").is_file() for flag in (0, 1)),
            "image_path": f"{image_prefix}/{name}.png",
        }


def _validate_name(name: str) -> str:
    normalized = name.strip()
    if (
        not normalized
        or normalized in {".", ".."}
        or len(normalized) > 100
        or normalized.endswith(".")
        or any(character in INVALID_NAME_CHARACTERS or ord(character) < 32 for character in normalized)
    ):
        raise AppError(
            ErrorCode.DATA_FILE_INVALID,
            "Equip template name is invalid.",
            {"name": name},
        )
    return normalized


def _load_image(data: bytes, field: str) -> Image.Image:
    if len(data) > 20 * 1024 * 1024:
        raise AppError(
            ErrorCode.DATA_FILE_INVALID,
            "Equip image exceeds the 20 MB limit.",
            {"field": field},
        )
    try:
        with Image.open(BytesIO(data)) as source:
            source.load()
            if source.width <= 0 or source.height <= 0 or source.width > 8192 or source.height > 8192:
                raise ValueError("Image dimensions are outside the supported range.")
            mode = "RGBA" if "A" in source.getbands() else "RGB"
            return source.convert(mode)
    except (OSError, UnidentifiedImageError, ValueError) as exc:
        raise AppError(
            ErrorCode.DATA_FILE_INVALID,
            "Equip image is not a supported image.",
            {"field": field},
        ) from exc


def _save_png_atomic(image: Image.Image | None, path: Path) -> None:
    if image is None:
        raise ValueError("Image is required.")
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=f".{path.stem}-",
            suffix=".tmp",
            dir=path.parent,
            delete=False,
        ) as temporary:
            image.save(temporary, format="PNG")
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = Path(temporary.name)
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _reserve_temporary_path(path: Path, *, suffix: str) -> Path:
    with tempfile.NamedTemporaryFile(
        prefix=f".{path.stem}-",
        suffix=suffix,
        dir=path.parent,
        delete=False,
    ) as temporary:
        temporary_path = Path(temporary.name)
    temporary_path.unlink()
    return temporary_path


def _box_inside(box: tuple[int, int, int, int], image_size: tuple[int, int]) -> bool:
    left, top, right, bottom = box
    width, height = image_size
    return 0 <= left < right <= width and 0 <= top < bottom <= height


def _encode_png(image: Image.Image) -> bytes:
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _check_roi(top_left: list[int], scale: float) -> tuple[int, int, int, int]:
    full_left = top_left[0] - MAIN_MATCH_BOX[0] * scale
    full_top = top_left[1] - MAIN_MATCH_BOX[1] * scale
    left = round(full_left + CHECK_BOX[0] * scale)
    top = round(full_top + CHECK_BOX[1] * scale)
    width = max(round((CHECK_BOX[2] - CHECK_BOX[0]) * scale), 1)
    height = max(round((CHECK_BOX[3] - CHECK_BOX[1]) * scale), 1)
    return left, top, width, height


def _roi_inside(
    roi: tuple[int, int, int, int],
    image_size: tuple[int, int],
) -> bool:
    left, top, width, height = roi
    image_width, image_height = image_size
    return (
        left >= 0
        and top >= 0
        and width > 0
        and height > 0
        and left + width <= image_width
        and top + height <= image_height
    )
