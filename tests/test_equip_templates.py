from pathlib import Path

import pytest
from PIL import Image

from webapp.core.errors import AppError, ErrorCode
from webapp.services.equip_templates import EquipTemplateService
from webapp.services.resources import ResourceService


def test_move_backup_failure_restores_destination_without_temp_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assets = tmp_path / "assets"
    data = tmp_path / "data"
    assets.mkdir()
    data.mkdir()
    resources = ResourceService(assets, data)
    service = EquipTemplateService(resources)
    source = _png_bytes("blue")
    destination = _png_bytes("red")
    service.build("Event CE", full_image=destination, non_full_image=destination)
    service.activate("Event CE")
    service.build("Event CE", full_image=source, non_full_image=source)

    import webapp.services.equip_templates as module

    real_replace = module.os.replace
    destination_check = assets / "assist" / "equip_check" / "Event CE_0.png"

    def fail_during_backup(source_path: Path, destination_path: Path) -> None:
        if Path(source_path) == destination_check and str(destination_path).endswith(".backup"):
            raise OSError("simulated backup failure")
        real_replace(source_path, destination_path)

    monkeypatch.setattr(module.os, "replace", fail_during_backup)

    with pytest.raises(AppError) as exc_info:
        service.activate("Event CE", overwrite=True)

    assert exc_info.value.code == ErrorCode.DATA_FILE_INVALID
    assert Image.open(assets / "assist" / "assist_equip" / "Event CE.png").getpixel((0, 0)) == (
        255,
        0,
        0,
    )
    assert (assets / "assist" / "equip_check" / "Event CE_0.png").is_file()
    assert (assets / "equipmaker" / "assist_equip_store" / "Event CE.png").is_file()
    assert list(assets.rglob("*.backup")) == []


def _png_bytes(color: str) -> bytes:
    from io import BytesIO

    output = BytesIO()
    Image.new("RGB", (237, 68), color).save(output, format="PNG")
    return output.getvalue()
