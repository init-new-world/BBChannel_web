from __future__ import annotations

from io import BytesIO
from pathlib import Path, PurePosixPath

from PIL import Image, UnidentifiedImageError

from webapp.core.errors import AppError, ErrorCode
from webapp.services.resources import ResourceService


class DropTemplateService:
    def __init__(self, resources: ResourceService) -> None:
        self._resources = resources

    def catalog(self, configured: object = None) -> dict[str, object]:
        return {"templates": self._paths(), "resolved_path": self.resolve(configured)}

    def _paths(self) -> list[str]:
        return [path for path in self._resources.list_templates() if path.startswith("drop/")]

    def resolve(self, configured: object) -> str | None:
        if not isinstance(configured, str) or not configured.strip() or "\x00" in configured:
            return None
        parts = PurePosixPath(configured.strip().replace("\\", "/")).parts
        if not parts or ".." in parts:
            return None
        folded = [part.casefold() for part in parts]
        relative = None
        if folded[0] == "drop":
            relative = "/".join(parts)
        else:
            for index in range(len(parts) - 1):
                if folded[index:index + 2] == ["assets", "drop"]:
                    relative = "/".join(parts[index + 1:])
                    break
        paths = self._paths()
        if relative is not None:
            matches = [path for path in paths if path.casefold() == relative.casefold()]
            selected = relative if relative in paths else matches[0] if len(matches) == 1 else None
        else:
            matches = [path for path in paths if PurePosixPath(path).name.casefold() == folded[-1]]
            selected = matches[0] if len(matches) == 1 else None
        if selected is not None:
            try:
                self._resolve_file(selected)
            except AppError as exc:
                if exc.code != ErrorCode.TEMPLATE_NOT_FOUND:
                    raise
                return None
        return selected

    def _resolve_file(self, path: str) -> Path:
        image_path = self._resources.resolve_template(path)
        if not image_path.is_relative_to(self._resources.assets_dir / "drop"):
            raise AppError(ErrorCode.TEMPLATE_NOT_FOUND, "Drop template not found.")
        return image_path

    def read_image(self, path: str) -> bytes:
        parts = PurePosixPath(path).parts
        if not path.startswith("drop/") or ".." in parts or "\\" in path or "\x00" in path:
            raise AppError(ErrorCode.TEMPLATE_NOT_FOUND, "Drop template not found.")
        image_path = self._resolve_file(path)
        try:
            with Image.open(image_path) as image:
                output = BytesIO()
                image.convert("RGBA").save(output, format="PNG")
                return output.getvalue()
        except (OSError, UnidentifiedImageError) as exc:
            raise AppError(ErrorCode.TEMPLATE_LOAD_FAILED, "Drop template image could not be loaded.") from exc
