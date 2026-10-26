from __future__ import annotations

from io import BytesIO

from PIL import Image, UnidentifiedImageError

from webapp.core.errors import AppError, ErrorCode
from webapp.services.resources import ResourceService
from webapp.services.script_data import ScriptDataService


class MasterPortraitService:
    def __init__(self, resources: ResourceService, script_data: ScriptDataService) -> None:
        self._resources = resources
        self._script_data = script_data

    def read_image(self, equip: str, sex: int = 0) -> bytes:
        if isinstance(sex, bool) or not isinstance(sex, int) or sex not in (0, 1):
            raise AppError(ErrorCode.TEMPLATE_NOT_FOUND, "Master portrait not found.")
        master = next((item for item in self._script_data.list_masters()["masters"] if str(item["sn"]) == equip), None)
        name = master["name"] if master else None
        if (not isinstance(name, str) or not name or name in (".", "..")
                or any(character in name for character in ("/", "\\", ":", "\x00"))):
            raise AppError(ErrorCode.TEMPLATE_NOT_FOUND, "Master portrait not found.")
        sn = master["sn"]
        if isinstance(sn, bool) or not isinstance(sn, (int, str)) or sn == "":
            raise AppError(ErrorCode.TEMPLATE_NOT_FOUND, "Master portrait not found.")
        path = self._resources.resolve_template(f"masterface/{name}_{sex}.png")
        if not path.is_relative_to(self._resources.assets_dir / "masterface"):
            raise AppError(ErrorCode.TEMPLATE_NOT_FOUND, "Master portrait not found.")
        try:
            with Image.open(path) as image:
                output = BytesIO()
                image.convert("RGBA").save(output, format="PNG")
                return output.getvalue()
        except (OSError, UnidentifiedImageError) as exc:
            raise AppError(ErrorCode.TEMPLATE_LOAD_FAILED, "Master portrait image could not be loaded.") from exc
