from __future__ import annotations

from pathlib import Path

from webapp.core.errors import AppError, ErrorCode


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".ico"}


class ResourceService:
    def __init__(self, assets_dir: Path | str, data_dir: Path | str) -> None:
        self.assets_dir = Path(assets_dir).resolve()
        self.data_dir = Path(data_dir).resolve()

    def list_templates(self) -> list[str]:
        if not self.assets_dir.exists():
            return []
        templates: list[str] = []
        for path in self.assets_dir.rglob("*"):
            if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS:
                templates.append(path.relative_to(self.assets_dir).as_posix())
        return sorted(templates)

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
