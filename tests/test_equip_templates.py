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


def test_simple_template_uses_star_marker_for_limit_break(tmp_path: Path) -> None:
    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    import random
    from io import BytesIO

    assets = tmp_path / "assets"
    data = tmp_path / "data"
    check_dir = assets / "assist" / "equip_check"
    check_dir.mkdir(parents=True)
    data.mkdir()
    randomizer = random.Random(71)
    template = Image.new("RGB", (237, 68))
    template.putdata(
        [
            tuple(randomizer.randrange(256) for _channel in range(3))
            for _pixel in range(237 * 68)
        ]
    )
    star = template.crop((194, 34, 228, 68))
    star.save(check_dir / "star.png")
    Image.new("L", star.size, 255).save(check_dir / "starMask.png")
    resources = ResourceService(assets, data)
    service = EquipTemplateService(resources)
    source = BytesIO()
    template.save(source, format="PNG")
    service.build("Event CE", full_image=source.getvalue(), non_full_image=None)

    scale = 2 / 3
    screenshot = Image.new("RGB", (1280, 720), (18, 24, 32))
    main = Image.fromarray(
        cv2.resize(
            np.asarray(template.crop((39, 0, 194, 56))),
            (round(155 * scale), round(56 * scale)),
            interpolation=cv2.INTER_AREA,
        )
    )
    scaled_star = Image.fromarray(
        cv2.resize(
            np.asarray(star),
            (round(34 * scale), round(34 * scale)),
            interpolation=cv2.INTER_AREA,
        )
    )
    screenshot.paste(main, (126, 250))
    screenshot.paste(scaled_star, (229, 273))
    screenshot_bytes = BytesIO()
    screenshot.save(screenshot_bytes, format="PNG")

    result = service.test_template(
        "Event CE",
        location="archive",
        screenshot=screenshot_bytes.getvalue(),
        threshold=0.99,
    )

    assert result["precise"] is False
    assert result["match_count"] == 1
    assert result["matches"][0]["full_limit_break"] is True
    assert result["matches"][0]["limit_break_method"] == "star_marker"


def _png_bytes(color: str) -> bytes:
    from io import BytesIO

    output = BytesIO()
    Image.new("RGB", (237, 68), color).save(output, format="PNG")
    return output.getvalue()
