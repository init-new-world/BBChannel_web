from __future__ import annotations

import os
import re
import tempfile
from dataclasses import dataclass
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from threading import RLock

from PIL import Image, UnidentifiedImageError

from webapp.core.errors import AppError, ErrorCode
from webapp.services.resources import ResourceService


IMAGE_TAG_NAME_RE = re.compile(
    r"^W(?P<W>-?\d+)H(?P<H>-?\d+)"
    r"DXL(?P<DXL>-?\d+)DXR(?P<DXR>-?\d+)"
    r"DYT(?P<DYT>-?\d+)DYB(?P<DYB>-?\d+)CON(?P<CON>\d+)$"
)
INVALID_LABEL_CHARACTERS = set('<>:"/\\|?*[]')


@dataclass(frozen=True)
class ImageTagMetadata:
    name: str
    source_width: int
    source_height: int
    left: int
    right: int
    top: int
    bottom: int
    threshold: float

    @property
    def image_size(self) -> tuple[int, int]:
        return self.right - self.left, self.bottom - self.top

    def plan_entry(self, template_path: str) -> dict[str, object]:
        return {
            "template_name": self.name,
            "template_path": template_path,
            "threshold": self.threshold,
            "source_width": self.source_width,
            "source_height": self.source_height,
            "left": self.left,
            "right": self.right,
            "top": self.top,
            "bottom": self.bottom,
        }


def parse_image_tag_filename(name: str) -> ImageTagMetadata:
    if (
        not isinstance(name, str)
        or not name
        or Path(name).name != name
        or "\\" in name
        or Path(name).suffix.lower() != ".png"
    ):
        raise ValueError("has an invalid filename.")
    metadata_stem = Path(name).stem.rsplit("]", 1)[-1]
    match = IMAGE_TAG_NAME_RE.fullmatch(metadata_stem)
    if match is None:
        raise ValueError("has an invalid filename.")
    values = {key: int(value) for key, value in match.groupdict().items() if key != "CON"}
    threshold = float(f"0.{match.group('CON')}")
    if (
        values["W"] <= 0
        or values["H"] <= 0
        or values["DXL"] >= values["DXR"]
        or values["DYT"] >= values["DYB"]
        or not 0 <= threshold <= 1
    ):
        raise ValueError("has invalid metadata.")
    return ImageTagMetadata(
        name=name,
        source_width=values["W"],
        source_height=values["H"],
        left=values["DXL"],
        right=values["DXR"],
        top=values["DYT"],
        bottom=values["DYB"],
        threshold=threshold,
    )


class ImageTagService:
    def __init__(self, resources: ResourceService, *, directory: str, kind: str) -> None:
        self._resources = resources
        self._relative_directory = directory
        self._directory = resources.assets_dir / directory
        self._kind = kind
        self._lock = RLock()

    def inventory(self) -> list[dict[str, object]]:
        with self._lock:
            try:
                self._check_path(self._directory)
            except AppError:
                return []
            if not self._directory.exists():
                return []
            entries = []
            for path in sorted(self._directory.iterdir(), key=lambda item: item.name.casefold()):
                if not path.is_file() or path.suffix.lower() != ".png":
                    continue
                try:
                    entries.append(self._describe(path))
                except AppError:
                    continue
            return entries

    def build(
        self,
        *,
        label: str,
        screenshot: bytes,
        anchor: list[int],
        bounds: list[int],
        threshold: float,
        overwrite: bool = False,
    ) -> dict[str, object]:
        source = _load_image(screenshot, "screenshot_base64")
        anchor_x, anchor_y = _point(anchor, "anchor")
        left, top, right, bottom = _bounds(bounds, source.size)
        if not (0 <= anchor_x < source.width and 0 <= anchor_y < source.height):
            raise AppError(
                ErrorCode.DATA_FILE_INVALID,
                f"{self._kind} anchor must be inside the screenshot.",
                {"anchor": [anchor_x, anchor_y], "image_size": list(source.size)},
            )
        normalized_label = _label(label)
        confidence = _confidence_code(threshold)
        name = (
            f"[{normalized_label}]W{source.width}H{source.height}"
            f"DXL{left - anchor_x}DXR{right - anchor_x}"
            f"DYT{top - anchor_y}DYB{bottom - anchor_y}CON{confidence}.png"
        )
        return self._save(
            name,
            source.crop((left, top, right, bottom)),
            overwrite=overwrite,
        )

    def import_image(
        self,
        name: str,
        image: bytes,
        *,
        overwrite: bool = False,
    ) -> dict[str, object]:
        metadata = _metadata(name, self._kind)
        source = _load_image(image, "image_base64")
        if source.size != metadata.image_size:
            raise AppError(
                ErrorCode.DATA_FILE_INVALID,
                f"{self._kind} image dimensions do not match its filename metadata.",
                {
                    "name": name,
                    "expected_size": list(metadata.image_size),
                    "actual_size": list(source.size),
                },
            )
        return self._save(name, source, overwrite=overwrite)

    def read_image(self, name: str) -> bytes:
        with self._lock:
            path = self._path(name)
            if not path.is_file():
                raise AppError(
                    ErrorCode.DATA_FILE_NOT_FOUND,
                    f"{self._kind} was not found: {name}",
                    {"name": name},
                )
            return path.read_bytes()

    def delete(self, name: str) -> dict[str, object]:
        with self._lock:
            path = self._path(name)
            if not path.is_file():
                raise AppError(
                    ErrorCode.DATA_FILE_NOT_FOUND,
                    f"{self._kind} was not found: {name}",
                    {"name": name},
                )
            path.unlink()
            self._resources.refresh_template_index()
            return {"name": name, "deleted": True}

    def _save(
        self,
        name: str,
        image: Image.Image,
        *,
        overwrite: bool,
    ) -> dict[str, object]:
        metadata = _metadata(name, self._kind)
        if image.size != metadata.image_size:
            raise AppError(
                ErrorCode.DATA_FILE_INVALID,
                f"{self._kind} image dimensions do not match its filename metadata.",
                {
                    "name": name,
                    "expected_size": list(metadata.image_size),
                    "actual_size": list(image.size),
                },
            )
        with self._lock:
            path = self._path(name)
            self._directory.mkdir(parents=True, exist_ok=True)
            if path.exists() and not overwrite:
                raise AppError(
                    ErrorCode.DATA_FILE_CONFLICT,
                    f"{self._kind} already exists: {name}",
                    {"name": name},
                )
            _save_png_atomic(image, path)
            self._resources.refresh_template_index()
            return self._describe(path)

    def _describe(self, path: Path) -> dict[str, object]:
        self._check_path(path)
        metadata = _metadata(path.name, self._kind)
        try:
            with Image.open(path) as image:
                image_size = list(image.size)
        except (OSError, UnidentifiedImageError) as exc:
            raise AppError(
                ErrorCode.TEMPLATE_LOAD_FAILED,
                f"{self._kind} image could not be loaded: {path.name}",
                {"name": path.name},
            ) from exc
        return {
            "name": path.name,
            "template_path": f"{self._relative_directory}/{path.name}",
            "threshold": metadata.threshold,
            "source_size": [metadata.source_width, metadata.source_height],
            "offsets": [metadata.left, metadata.top, metadata.right, metadata.bottom],
            "image_size": image_size,
            "size_bytes": path.stat().st_size,
        }

    def _path(self, name: str) -> Path:
        _metadata(name, self._kind)
        path = self._directory / name
        self._check_path(path)
        return path

    def _check_path(self, path: Path) -> None:
        if any(candidate.is_symlink() for candidate in (
            path, self._directory, self._directory.parent,
        )):
            raise AppError(
                ErrorCode.DATA_FILE_INVALID,
                f"{self._kind} paths must not contain symbolic links.",
                {"name": path.name},
            )


def _metadata(name: str, kind: str) -> ImageTagMetadata:
    try:
        return parse_image_tag_filename(name)
    except ValueError as exc:
        raise AppError(
            ErrorCode.DATA_FILE_INVALID,
            f"{kind} filename {exc}",
            {"name": name},
        ) from exc


def _load_image(data: bytes, field: str) -> Image.Image:
    try:
        with Image.open(BytesIO(data)) as source:
            source.load()
            return source.convert("RGB")
    except (OSError, UnidentifiedImageError) as exc:
        raise AppError(
            ErrorCode.DATA_FILE_INVALID,
            "Image tag payload is not a valid image.",
            {"field": field},
        ) from exc


def _point(values: list[int], field: str) -> tuple[int, int]:
    if (
        not isinstance(values, list)
        or len(values) != 2
        or any(isinstance(value, bool) or not isinstance(value, int) for value in values)
    ):
        raise AppError(
            ErrorCode.DATA_FILE_INVALID,
            f"Image tag {field} must contain two integer coordinates.",
            {field: values},
        )
    return values[0], values[1]


def _bounds(values: list[int], image_size: tuple[int, int]) -> tuple[int, int, int, int]:
    if (
        not isinstance(values, list)
        or len(values) != 4
        or any(isinstance(value, bool) or not isinstance(value, int) for value in values)
    ):
        raise AppError(
            ErrorCode.DATA_FILE_INVALID,
            "Image tag bounds must contain four integer coordinates.",
            {"bounds": values},
        )
    left, top, right, bottom = values
    if not (0 <= left < right <= image_size[0] and 0 <= top < bottom <= image_size[1]):
        raise AppError(
            ErrorCode.DATA_FILE_INVALID,
            "Image tag bounds must be inside the screenshot.",
            {"bounds": values, "image_size": list(image_size)},
        )
    return left, top, right, bottom


def _label(value: str) -> str:
    label = value.strip() if isinstance(value, str) else ""
    if (
        not label
        or len(label) > 64
        or any(character in INVALID_LABEL_CHARACTERS or ord(character) < 32 for character in label)
    ):
        raise AppError(
            ErrorCode.DATA_FILE_INVALID,
            "Image tag label is invalid.",
            {"label": value},
        )
    return label


def _confidence_code(value: float) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 < value < 1:
        raise AppError(
            ErrorCode.DATA_FILE_INVALID,
            "Image tag threshold must be greater than 0 and less than 1.",
            {"threshold": value},
        )
    code = format(Decimal(str(value)), "f").split(".", 1)[1].rstrip("0")
    if len(code) > 16:
        raise AppError(
            ErrorCode.DATA_FILE_INVALID,
            "Image tag threshold precision must not exceed 16 decimal places.",
            {"threshold": value},
        )
    return code


def _save_png_atomic(image: Image.Image, path: Path) -> None:
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
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
