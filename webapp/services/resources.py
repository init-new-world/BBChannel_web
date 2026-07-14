from __future__ import annotations

import os
from pathlib import Path
from threading import RLock

from PIL import Image, UnidentifiedImageError

from webapp.core.errors import AppError, ErrorCode


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".ico"}


class ResourceService:
    def __init__(self, assets_dir: Path | str, data_dir: Path | str) -> None:
        self.assets_dir = Path(assets_dir).resolve()
        self.data_dir = Path(data_dir).resolve()
        self._index_lock = RLock()
        self._template_entries: list[dict[str, object]] | None = None

    def list_templates(self) -> list[str]:
        return [str(entry["path"]) for entry in self._index()]

    def template_index(
        self,
        *,
        prefix: str | None = None,
        query: str | None = None,
        offset: int = 0,
        limit: int = 200,
    ) -> dict[str, object]:
        entries = self._index()
        normalized_prefix = (prefix or "").strip().strip("/")
        if normalized_prefix:
            prefix_with_separator = f"{normalized_prefix}/"
            entries = [
                entry
                for entry in entries
                if entry["path"] == normalized_prefix
                or str(entry["path"]).startswith(prefix_with_separator)
            ]
        normalized_query = (query or "").strip().casefold()
        if normalized_query:
            entries = [
                entry
                for entry in entries
                if normalized_query in str(entry["path"]).casefold()
            ]
        offset = max(offset, 0)
        limit = max(limit, 1)
        total = len(entries)
        return {
            "total": total,
            "offset": offset,
            "limit": limit,
            "entries": [dict(entry) for entry in entries[offset : offset + limit]],
        }

    def template_metadata(self, template_path: str) -> dict[str, object]:
        template_file = self.resolve_template(template_path)
        try:
            with Image.open(template_file) as image:
                width, height = image.size
                mode = image.mode
                image_format = image.format
        except (OSError, UnidentifiedImageError) as exc:
            raise AppError(
                ErrorCode.TEMPLATE_LOAD_FAILED,
                f"Template image could not be loaded: {template_path}",
                {"template_path": template_path, "error": str(exc)},
            ) from exc
        stat = template_file.stat()
        relative_path = template_file.relative_to(self.assets_dir).as_posix()
        return {
            **self._entry_for(relative_path, template_file.suffix, stat.st_size),
            "width": width,
            "height": height,
            "mode": mode,
            "format": image_format,
        }

    def refresh_template_index(self) -> int:
        with self._index_lock:
            self._template_entries = self._build_index()
            return len(self._template_entries)

    def resolve_template(self, template_path: str) -> Path:
        candidate = (self.assets_dir / template_path).resolve()
        if not self._is_inside_assets(candidate) or not candidate.is_file():
            raise AppError(
                ErrorCode.TEMPLATE_NOT_FOUND,
                f"Template not found: {template_path}",
                {"template_path": template_path},
            )
        if candidate.suffix.lower() not in IMAGE_EXTENSIONS:
            raise AppError(
                ErrorCode.TEMPLATE_LOAD_FAILED,
                f"Unsupported template type: {template_path}",
                {"template_path": template_path},
            )
        return candidate

    def _is_inside_assets(self, path: Path) -> bool:
        try:
            path.relative_to(self.assets_dir)
        except ValueError:
            return False
        return True

    def _index(self) -> list[dict[str, object]]:
        with self._index_lock:
            if self._template_entries is None:
                self._template_entries = self._build_index()
            return list(self._template_entries)

    def _build_index(self) -> list[dict[str, object]]:
        if not self.assets_dir.exists():
            return []
        entries: list[dict[str, object]] = []
        pending_directories = [self.assets_dir]
        while pending_directories:
            directory = pending_directories.pop()
            with os.scandir(directory) as directory_entries:
                for entry in directory_entries:
                    if entry.is_dir(follow_symlinks=False):
                        pending_directories.append(Path(entry.path))
                        continue
                    extension = Path(entry.name).suffix.lower()
                    if not entry.is_file(follow_symlinks=False) or extension not in IMAGE_EXTENSIONS:
                        continue
                    path = Path(entry.path)
                    relative_path = path.relative_to(self.assets_dir).as_posix()
                    entries.append(
                        self._entry_for(
                            relative_path,
                            extension,
                            entry.stat(follow_symlinks=False).st_size,
                        )
                    )
        return sorted(entries, key=lambda entry: str(entry["path"]))

    @staticmethod
    def _entry_for(path: str, extension: str, size_bytes: int) -> dict[str, object]:
        category, separator, _ = path.partition("/")
        return {
            "path": path,
            "category": category if separator else "",
            "extension": extension.lower(),
            "size_bytes": size_bytes,
        }
